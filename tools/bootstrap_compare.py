"""Compare native bootstrap artifacts, normalizing only documented PE times."""
import hashlib
import struct


def normalize_native(content):
    """ELF stays exact. PE ignores only COFF/debug-directory TimeDateStamp.

    Section contents, checksums, GUIDs and other metadata are never masked.
    Each returned field identifies its exact file offset and original value.
    """
    if content.startswith(b'\x7fELF'):
        return content, []
    if not content.startswith(b'MZ'):
        raise ValueError('bootstrap artifact is neither ELF nor PE')

    def read(format, offset):
        if offset < 0 or offset+struct.calcsize(format) > len(content):
            raise ValueError('truncated PE bootstrap artifact')
        return struct.unpack_from(format, content, offset)

    pe, = read('<I', 0x3c)
    if content[pe:pe+4] != b'PE\0\0':
        raise ValueError('invalid PE signature')
    count, = read('<H', pe+6)
    optional_size, = read('<H', pe+20)
    optional = pe+24
    magic, = read('<H', optional)
    if magic != 0x20b or optional_size < 112+7*8:
        raise ValueError('bootstrap requires PE32+ with a debug data directory')
    sections = []
    for index in range(count):
        virtual_size, rva, size, offset = read('<IIII', optional+optional_size+40*index+8)
        if offset+size > len(content):
            raise ValueError('PE section extends past end of file')
        sections.append((rva, virtual_size, offset, size))
    fields = [{'field': 'IMAGE_FILE_HEADER.TimeDateStamp', 'offset': pe+8}]
    debug_rva, debug_size = read('<II', optional+112+6*8)
    if debug_size:
        if debug_size % 28:
            raise ValueError('invalid PE debug directory size')
        offset = next((offset+debug_rva-rva for rva, _, offset, size in sections
                       if rva <= debug_rva and debug_rva+debug_size <= rva+size), None)
        if offset is None:
            raise ValueError('PE debug directory is not backed by section data')
        for index in range(debug_size//28):
            fields.append({'field': f'IMAGE_DEBUG_DIRECTORY[{index}].TimeDateStamp',
                           'offset': offset+28*index+4})
    normalized = bytearray(content)
    for field in fields:
        field['value'], = read('<I', field['offset'])
        normalized[field['offset']:field['offset']+4] = b'\0'*4
    return bytes(normalized), fields


def compare_native(first, second):
    normalized = [normalize_native(content) for content in (first, second)]
    return {'raw_equal': first == second,
            'raw_sha256': [hashlib.sha256(content).hexdigest() for content in (first, second)],
            'normalized_equal': normalized[0][0] == normalized[1][0],
            'normalized_sha256': [hashlib.sha256(content).hexdigest() for content, _ in normalized],
            'normalization': [fields for _, fields in normalized]}
