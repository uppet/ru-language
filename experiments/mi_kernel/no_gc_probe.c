#include "kernel.h"
MiResult exported_probe(MiOwner *o, uint32_t offset, uint32_t length, uint32_t seed) { return mi_scan(o,offset,length,seed); }
