"""Detailed diagnostics use authored loopback Responses, never real credentials."""
import json
import threading
import time
import unittest
from unittest.mock import patch

from rulang.generation import GenerationConfig, LOCAL_TEST_API_KEY, GenerationError, request_response
from rulang.generation_trace import GenerationTrace, TraceStore, MAX_EVENT_BYTES, MAX_TRACE_BYTES
from rushu import generation
from rushu.kernel import KernelError
from test_generation import MockResponses, response_for
import test_rushu_source_generation as notebook_tests
PROMPT = notebook_tests.PROMPT

ID = 'a' * 32


class TraceTests(unittest.TestCase):
    def call(self, mock, target='python'):
        with mock as provider:
            with patch.object(generation, 'load_config', return_value=GenerationConfig(LOCAL_TEST_API_KEY, provider.base)):
                try:
                    result = generation.generate_source({'prompt': PROMPT, 'generation_id': ID, 'runtime_target': target})
                except KernelError as error:
                    result = {'error': str(error), 'trace': error.trace}
            self.assertEqual(len(provider.requests), 1)
        return result

    def test_success_actual_text_extraction_and_nonexecuting_validation(self):
        raw = '```ru\n显 1/0.\n```'
        value = self.call(MockResponses(response_for(raw)))
        self.assertTrue(value['valid'])
        events = value['trace']['events']
        self.assertEqual(next(e['text'] for e in events if e['stage'] == 'model_text'), raw)
        self.assertEqual(next(e['text'] for e in events if e['stage'] == 'extracted_source'), '显 1/0.\n')
        self.assertEqual(events[-1]['stage'], 'final_success')
        self.assertEqual([e['seq'] for e in events], list(range(1, len(events)+1)))
        self.assertTrue(all(e['elapsed_ms'] >= 0 and '+00:00' in e['time'] for e in events))

    def test_extraction_failure_preserves_provider_text(self):
        raw = '```ru\n显 42.\n```\nextra prose'
        value = self.call(MockResponses(response_for(raw)))
        self.assertIn('error', value)
        self.assertIn(raw, [e.get('text') for e in value['trace']['events']])
        self.assertTrue(any('围栏无效' in e['detail'] for e in value['trace']['events']))

    def test_compile_failure_retains_both_texts(self):
        value = self.call(MockResponses(response_for("问 '不要执行'.")), 'browser-js')
        self.assertFalse(value['valid'])
        self.assertEqual(value['trace']['events'][-1]['stage'], 'final_failure')
        self.assertIn('extracted_source', [e['stage'] for e in value['trace']['events']])

    def test_refusal_incomplete_missing_output_and_malformed_json(self):
        refusal = response_for('partial', status='incomplete', incomplete_details={'reason':'max_output_tokens'})
        refusal['output'][0]['content'].append({'type':'refusal','refusal':'authored refusal'})
        value = self.call(MockResponses(refusal))
        stages = [e['stage'] for e in value['trace']['events']]
        for stage in ('incomplete','refusal','model_text','final_failure'):
            self.assertIn(stage, stages)
        for mock in (MockResponses({'status':'completed','output':[]}), MockResponses(raw=b'{bad json')):
            value = self.call(mock)
            self.assertIn('error', value)
            self.assertTrue(value['trace']['complete'])

    def test_redaction_error_headers_and_reasoning(self):
        secret = LOCAL_TEST_API_KEY
        raw = f'显 "{secret}".\nAuthorization: Bearer OTHER_SECRET\nCookie: session=PRIVATE_COOKIE\nhttps://name:password@example.test/path?secret=PRIVATE_URL'
        value = response_for(raw)
        value['output'].insert(0, {'type':'reasoning','encrypted_content':'PRIVATE_REASONING','summary':'PRIVATE_SUMMARY'})
        result = self.call(MockResponses(value, headers={'x-request-id':secret, 'Set-Cookie':'PRIVATE_HEADER'}))
        serialized = json.dumps(result)
        for hidden in (secret,'OTHER_SECRET','PRIVATE_COOKIE','PRIVATE_URL','PRIVATE_REASONING','PRIVATE_SUMMARY','PRIVATE_HEADER'):
            self.assertNotIn(hidden, serialized)
        self.assertIn('[REDACTED]', serialized)
        boundary = 'x' * 4090 + secret
        result = self.call(MockResponses({'error':{'message': boundary}}, status=400))
        self.assertNotIn(secret, json.dumps(result))
        self.assertIn('[REDACTED]', json.dumps(result))
        for status in (400,429):
            result = self.call(MockResponses({'error':{'message':f'bad {secret} https://x/?token=PRIVATE_URL','code':'test_error','type':'request_error'}, 'extra':'PRIVATE_EXTRA'},status=status))
            serialized = json.dumps(result)
            self.assertNotIn(secret, serialized)
            self.assertNotIn('PRIVATE_URL', serialized)
            self.assertNotIn('PRIVATE_EXTRA', serialized)
            self.assertIn(f'HTTP {status}', serialized)
            self.assertIn('test_error', serialized)

    def test_timeout_and_network_failure_terminate_trace_without_raw_error(self):
        with MockResponses(response_for(), delay=.1) as provider:
            with patch.object(generation, 'load_config', return_value=GenerationConfig(LOCAL_TEST_API_KEY, provider.base)):
                with self.assertRaises(KernelError) as caught:
                    generation.generate_source({'prompt': PROMPT, 'generation_id': ID}, timeout=.02)
                self.assertTrue(caught.exception.trace['complete'])
            self.assertTrue(generation._GENERATION_SLOT.acquire(timeout=5))
            generation._GENERATION_SLOT.release()
        self.assertEqual(len(provider.requests), 1)
        for error in (TimeoutError('SECRET'), OSError('SECRET')):
            trace = GenerationTrace(ID)
            with patch('rulang.generation.urlrequest.build_opener') as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaises(GenerationError):
                    request_response(GenerationConfig('dummy-secret', 'https://example.test'), 'intent', trace=trace)
            self.assertNotIn('SECRET', json.dumps(trace.snapshot()))
            factory.return_value.open.assert_called_once()

    def test_utf8_caps_redact_before_truncation_incremental_and_clear(self):
        trace = GenerationTrace(ID)
        trace.protect('known-secret')
        trace.emit('model_text','actual', '如' * (MAX_EVENT_BYTES // 3) + 'known-secret')
        self.assertTrue(trace.snapshot()['truncated'])
        self.assertLessEqual(len(trace.snapshot()['events'][0]['text'].encode()), MAX_EVENT_BYTES)
        self.assertNotIn('known', json.dumps(trace.snapshot()))
        trace.emit('extracted_source','actual','x' * MAX_TRACE_BYTES)
        self.assertLessEqual(sum(len(e.get('text','').encode()) for e in trace.snapshot()['events']), MAX_TRACE_BYTES)
        self.assertEqual(len(trace.snapshot(after=1)['events']), 1)
        trace.clear()
        trace.emit('model_text','late', 'late')
        self.assertEqual(trace.snapshot()['events'], [])

    def test_store_claims_capacity_and_ttl(self):
        store = TraceStore()
        store.delete('c' * 32)
        cleared = store.create('c' * 32)
        cleared.emit('model_text', 'late', 'must not reappear')
        self.assertEqual(cleared.snapshot()['events'], [])
        self.assertIsNone(store.get('c' * 32))
        with self.assertRaises(ValueError): store.create('c' * 32)
        first = store.create(ID)
        store.delete(ID)
        with self.assertRaises(ValueError): store.create(ID)
        first.emit('model_text','late','must not reappear')
        self.assertIsNone(store.get(ID))
        for number in range(8): store.create(f'{number:032x}')
        with self.assertRaises(ValueError): store.create('b'*32)
        store.get('0'*32).emit('final_success','done')
        store.create('b'*32)
        self.assertIsNone(store.get('0'*32))
        store.get('b'*32).started -= 3601
        self.assertIsNone(store.get('b'*32))


class TraceAPITests(unittest.TestCase):
    setUp = notebook_tests.SourceGenerationTests.setUp
    tearDown = notebook_tests.SourceGenerationTests.tearDown
    request = notebook_tests.SourceGenerationTests.request

    def test_auth_origin_id_collision_poll_and_delete(self):
        with patch.object(generation,'request_response',return_value='显 42.'):
            status,value = self.request('/api/generate',{'prompt':PROMPT,'generation_id':ID})
        self.assertEqual(status,200)
        path = '/api/generation/trace/'+ID
        self.assertEqual(self.request(path,authenticated=False)[0],401)
        self.assertEqual(self.request(path,origin='https://evil.test')[0],403)
        status, trace = self.request(path+'?after=1')
        self.assertEqual(status,200)
        self.assertTrue(all(e['seq'] > 1 for e in trace['events']))
        self.assertEqual(self.request(path+'?after=-1')[0],400)
        self.assertEqual(self.request('/api/generate',{'prompt':PROMPT,'generation_id':ID})[0],409)
        self.assertEqual(self.request(path,{},method='DELETE')[0],200)
        self.assertEqual(self.request(path)[0],404)
        self.assertEqual(self.request('/api/generate',{'prompt':PROMPT,'generation_id':ID})[0],409)

    def test_live_poll_is_incremental_and_provider_called_once(self):
        identifier = 'd' * 32
        results = []
        with MockResponses(response_for('显 42.'), delay=.2) as provider:
            with patch.object(generation, 'load_config', return_value=GenerationConfig(LOCAL_TEST_API_KEY, provider.base)):
                worker = threading.Thread(target=lambda: results.append(self.request('/api/generate', {'prompt': PROMPT, 'generation_id': identifier})))
                worker.start()
                deadline = time.monotonic() + 3
                seen = []
                while time.monotonic() < deadline:
                    status, trace = self.request('/api/generation/trace/' + identifier)
                    if status == 200:
                        seen = [e['stage'] for e in trace['events']]
                        if 'waiting' in seen:
                            break
                    time.sleep(.005)
                self.assertIn('waiting', seen)
                self.assertNotIn('model_text', seen)
                seq = trace['events'][-1]['seq']
                worker.join(5)
                self.assertFalse(worker.is_alive())
                status, later = self.request('/api/generation/trace/' + identifier + '?after=' + str(seq))
                self.assertEqual(status, 200)
                self.assertTrue(all(e['seq'] > seq for e in later['events']))
                self.assertIn('model_text', [e['stage'] for e in later['events']])
                self.assertTrue(later['complete'])
        self.assertEqual(results[0][0], 200)
        self.assertEqual(len(provider.requests), 1)

    def test_timeout_freezes_trace_but_retains_busy_slot(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(5)
            kwargs['trace'].emit('model_text','late','late output')
            return '显 42.'
        self.server.generation_timeout = .05
        with patch.object(generation,'request_response',side_effect=blocked):
            try:
                status,value = self.request('/api/generate',{'prompt':PROMPT,'generation_id':ID})
                self.assertEqual(status,504)
                self.assertTrue(value['trace']['complete'])
                self.assertEqual(self.request('/api/generate',{'prompt':PROMPT})[0],429)
                self.request('/api/generation/trace/'+ID,{},method='DELETE')
            finally:
                release.set()
                self.assertTrue(generation._GENERATION_SLOT.acquire(timeout=5))
                generation._GENERATION_SLOT.release()
        self.assertEqual(self.request('/api/generation/trace/'+ID)[0],404)
