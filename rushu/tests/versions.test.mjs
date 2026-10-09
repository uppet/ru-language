import test from 'node:test';
import assert from 'node:assert/strict';
import {versionLabel} from '../static/versions.mjs';
test('actual distinct package versions, without hardcoded WIP',()=>{
  assert.equal(versionLabel({ru:'0.11.0',specification:'0.10.0',rushu:'0.1.0'}),'如 0.11.0 · 规范 0.10.0 · 如书 0.1.0');
});
test('missing and malformed versions are visibly unknown',()=>{
  assert.equal(versionLabel(null),'如 未知 · 规范 未知 · 如书 未知');
  assert.equal(versionLabel({ru:'<b>x</b>',specification:null,rushu:'0.1.0'}),'如 未知 · 规范 未知 · 如书 0.1.0');
});
