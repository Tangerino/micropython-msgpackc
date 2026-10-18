/*
 * This file is part of msgpackc, a MessagePack module for MicroPython.
 *
 * The MIT License (MIT)
 *
 * Copyright (c) 2026 Carlos Tangerino
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

// msgpackc: MessagePack (https://msgpack.org) for MicroPython, written in C.
//
// The Python API and its behaviour follow Peter Hinch's pure-Python umsgpack
// (https://github.com/peterhinch/micropython-msgpack), itself a port of Vanya
// Sergeev's u-msgpack-python. Same functions, options, exceptions and
// ext_serializable decorator, and byte-for-byte identical output, so one can
// replace the other. The encoder started as the msgpack accelerator of the
// coIoTe firmware.
//
// Design notes:
// - The encoder writes into a single growable buffer which becomes the
//   returned bytes object without a copy.
// - The decoder reads either straight from a buffer (loads, Unpacker) without
//   copying, or from a stream (load) reading exactly the bytes it needs.
// - Nothing is static state: the ext type registry lives in a heap module
//   placed in sys.modules, so a soft reset discards it with everything else.
// - Every length taken from the input is checked against the data really
//   available before it is used, so corrupt or hostile input raises an
//   exception instead of reading out of bounds or allocating huge buffers.

#include <stdint.h>
#include <string.h>

#include "py/runtime.h"
#include "py/builtin.h"
#include "py/mpz.h"
#include "py/objexcept.h"
#include "py/objint.h"
#include "py/objlist.h"
#include "py/objmodule.h"
#include "py/objstr.h"
#include "py/objtuple.h"
#include "py/objtype.h"
#include "py/stackctrl.h"
#include "py/stream.h"
#include "py/unicode.h"

// Maximum nesting of arrays and maps, for both packing and unpacking. Each
// level takes 80 to 128 bytes of C stack on an ESP32, whose MicroPython task
// has 16 KiB: 32 levels leave room for the VM, the GC and raising an exception
// at the deepest level. The same limit everywhere means that data packed on
// one port can be unpacked on any other. On ports with MICROPY_STACK_CHECK the
// stack is also checked at every level. Override with -DMSGPACKC_MAX_DEPTH=n.
#ifndef MSGPACKC_MAX_DEPTH
#define MSGPACKC_MAX_DEPTH (32)
#endif

// Map keys that already exist as qstrs reuse them instead of allocating a
// copy. Keys usually do: the application writes them as literals, which are
// qstrs (msg["temp"]). Other strings are not looked up: a lookup that fails
// walks the qstr pools, which costs more than the copy (measured on ESP32-P4).
#ifndef MSGPACKC_REUSE_QSTR
#define MSGPACKC_REUSE_QSTR (1)
#endif

/******************************************************************************/
// Exceptions: the same hierarchy as umsgpack.

#define MSGPACKC_EXCEPTION(name, base) \
    static MP_DEFINE_CONST_OBJ_TYPE(mp_type_msgpackc_##name, MP_QSTR_##name, MP_TYPE_FLAG_NONE, \
    make_new, mp_obj_exception_make_new, \
    print, mp_obj_exception_print, \
    attr, mp_obj_exception_attr, \
    parent, &base \
    )

MSGPACKC_EXCEPTION(PackException, mp_type_Exception);
MSGPACKC_EXCEPTION(UnpackException, mp_type_Exception);
MSGPACKC_EXCEPTION(UnsupportedTypeException, mp_type_msgpackc_PackException);
MSGPACKC_EXCEPTION(InsufficientDataException, mp_type_msgpackc_UnpackException);
MSGPACKC_EXCEPTION(InvalidStringException, mp_type_msgpackc_UnpackException);
MSGPACKC_EXCEPTION(ReservedCodeException, mp_type_msgpackc_UnpackException);
MSGPACKC_EXCEPTION(UnhashableKeyException, mp_type_msgpackc_UnpackException);
MSGPACKC_EXCEPTION(DuplicateKeyException, mp_type_msgpackc_UnpackException);

static MP_NORETURN void raise_insufficient(void) {
    mp_raise_type(&mp_type_msgpackc_InsufficientDataException);
}

static MP_NORETURN void raise_depth(void) {
    mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("maximum recursion depth exceeded"));
}

static MP_NORETURN void raise_changed(void) {
    mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("container changed size during packing"));
}

// Raise exc_type with the message: prefix + str(obj) + suffix, the
// equivalent of an f-string in umsgpack.
static MP_NORETURN void raise_with_obj(const mp_obj_type_t *exc_type, const char *prefix,
    mp_obj_t obj, mp_print_kind_t kind, const char *suffix) {
    vstr_t vstr;
    mp_print_t print;
    vstr_init_print(&vstr, 32, &print);
    mp_print_str(&print, prefix);
    mp_obj_print_helper(&print, obj, kind);
    mp_print_str(&print, suffix);
    nlr_raise(mp_obj_new_exception_arg1(exc_type, mp_obj_new_str_from_vstr(&vstr)));
}

static MP_NORETURN void raise_unsupported_type(mp_obj_t obj) {
    raise_with_obj(&mp_type_msgpackc_UnsupportedTypeException, "",
        MP_OBJ_FROM_PTR(mp_obj_get_type(obj)), PRINT_STR, "");
}

static MP_NORETURN void raise_unsupported_msg(mp_rom_error_text_t msg) {
    mp_raise_msg(&mp_type_msgpackc_UnsupportedTypeException, msg);
}

// Lengths above 32 bits cannot be encoded. Only possible where size_t is
// wider than 32 bits; elsewhere the test would be "always false" (a warning).
static inline bool len_exceeds_u32(size_t n) {
    #if SIZE_MAX > 0xffffffff
    return n > 0xffffffff;
    #else
    (void)n;
    return false;
    #endif
}

/******************************************************************************/
// Ext type registry (the ext_serializable decorator).
//
// umsgpack keeps three dicts: custom {user class: ext_type},
// builtins {type: (packer class, ext_type)} and packers {ext_type: class}.
// They are kept here as attributes of a heap module "_msgpackc_ext" stored in
// sys.modules: no root pointers are needed, and a soft reset (which empties
// sys.modules) drops them together with the classes they refer to.

static mp_obj_t ext_registry(bool create) {
    mp_map_t *mods = &MP_STATE_VM(mp_loaded_modules_dict).map;
    mp_map_elem_t *e = mp_map_lookup(mods, MP_OBJ_NEW_QSTR(MP_QSTR__msgpackc_ext), MP_MAP_LOOKUP);
    if (e != NULL && mp_obj_is_type(e->value, &mp_type_module)) {
        return e->value;
    }
    if (!create) {
        return MP_OBJ_NULL;
    }
    if (e != NULL) {
        mp_map_lookup(mods, MP_OBJ_NEW_QSTR(MP_QSTR__msgpackc_ext), MP_MAP_LOOKUP_REMOVE_IF_FOUND);
    }
    mp_obj_t mod = mp_obj_new_module(MP_QSTR__msgpackc_ext);
    mp_obj_t globals = MP_OBJ_FROM_PTR(mp_obj_module_get_globals(mod));
    mp_obj_dict_store(globals, MP_OBJ_NEW_QSTR(MP_QSTR_custom), mp_obj_new_dict(0));
    mp_obj_dict_store(globals, MP_OBJ_NEW_QSTR(MP_QSTR_builtins), mp_obj_new_dict(0));
    mp_obj_dict_store(globals, MP_OBJ_NEW_QSTR(MP_QSTR_packers), mp_obj_new_dict(0));
    return mod;
}

static mp_obj_t ext_dict(mp_obj_t reg, qstr name) {
    mp_obj_t globals = MP_OBJ_FROM_PTR(mp_obj_module_get_globals(reg));
    mp_obj_t d = mp_obj_dict_get(globals, MP_OBJ_NEW_QSTR(name));
    if (!mp_obj_is_dict_or_ordereddict(d)) {
        mp_raise_TypeError(MP_ERROR_TEXT("_msgpackc_ext registry damaged"));
    }
    return d;
}

// The map of a registry dict, or NULL if there is no registry or it is empty
// (the common case, which then costs nothing per packed object).
static mp_map_t *ext_map(qstr name) {
    mp_obj_t reg = ext_registry(false);
    if (reg == MP_OBJ_NULL) {
        return NULL;
    }
    mp_map_t *map = mp_obj_dict_get_map(ext_dict(reg, name));
    return map->used ? map : NULL;
}

// The dicts built from **options, handed to the ext packb/unpackb methods.
static mp_obj_t options_dict(mp_obj_t *options, mp_map_t *kw) {
    if (*options == MP_OBJ_NULL) {
        *options = mp_obj_new_dict(kw == NULL ? 0 : kw->used);
        if (kw != NULL) {
            for (size_t i = 0; i < kw->alloc; i++) {
                if (mp_map_slot_is_filled(kw, i)) {
                    mp_obj_dict_store(*options, kw->table[i].key, kw->table[i].value);
                }
            }
        }
    }
    return *options;
}

static mp_obj_t kw_get(mp_map_t *kw, qstr name) {
    if (kw == NULL || kw->used == 0) {
        return MP_OBJ_NULL;
    }
    mp_map_elem_t *e = mp_map_lookup(kw, MP_OBJ_NEW_QSTR(name), MP_MAP_LOOKUP);
    return e == NULL ? MP_OBJ_NULL : e->value;
}

static bool kw_flag(mp_map_t *kw, qstr name) {
    mp_obj_t v = kw_get(kw, name);
    return v != MP_OBJ_NULL && mp_obj_is_true(v);
}

/******************************************************************************/
// Packing

enum {
    FPREC_SINGLE,
    FPREC_DOUBLE,
    FPREC_INVALID,
};

#if MICROPY_FLOAT_IMPL == MICROPY_FLOAT_IMPL_DOUBLE
#define FPREC_NATIVE FPREC_DOUBLE
#define MSGPACKC_FLOAT_PRECISION MP_QSTR_double
#else
#define FPREC_NATIVE FPREC_SINGLE
#define MSGPACKC_FLOAT_PRECISION MP_QSTR_single
#endif

typedef struct _packer_t {
    vstr_t vstr;
    mp_map_t *kw;         // **options of dumps/dump
    mp_obj_t options;     // the same as a dict, built on first use
    mp_map_t *builtins;   // registered built-in ext types, NULL if none
    mp_map_t *custom;     // registered user classes, NULL if none
    uint16_t depth;
    uint8_t fprec;
} packer_t;

static void pk_obj(packer_t *p, mp_obj_t o);

// The output buffer at least doubles when it grows, so packing is linear in
// the output size (vstr itself grows by a constant amount).
static MP_NOINLINE void pk_grow(vstr_t *vstr, size_t n) {
    size_t need = vstr->len + n;
    size_t alloc = vstr->alloc * 2;
    if (alloc < need) {
        alloc = need;
    }
    vstr->buf = m_renew(char, vstr->buf, vstr->alloc, alloc);
    vstr->alloc = alloc;
}

static inline byte *pk_reserve(packer_t *p, size_t n) {
    vstr_t *vstr = &p->vstr;
    if (vstr->alloc - vstr->len < n) {
        pk_grow(vstr, n);
    }
    byte *b = (byte *)vstr->buf + vstr->len;
    vstr->len += n;
    return b;
}

static inline void pk_byte(packer_t *p, byte b) {
    *pk_reserve(p, 1) = b;
}

static inline void put_be32(byte *b, uint32_t x, size_t n) {
    while (n--) {
        b[n] = (byte)x;
        x >>= 8;
    }
}

static void put_be64(byte *b, uint64_t x) {
    put_be32(b, (uint32_t)(x >> 32), 4);
    put_be32(b + 4, (uint32_t)x, 4);
}

// tag followed by n big-endian bytes of x, and room for extra payload bytes.
static byte *pk_hdr(packer_t *p, byte tag, uint32_t x, size_t n, size_t extra) {
    byte *b = pk_reserve(p, 1 + n + extra);
    b[0] = tag;
    put_be32(b + 1, x, n);
    return b + 1 + n;
}

static void pk_hdr64(packer_t *p, byte tag, uint64_t x) {
    byte *b = pk_reserve(p, 9);
    b[0] = tag;
    put_be64(b + 1, x);
}

static void pk_int64(packer_t *p, int64_t x) {
    if (x >= 0) {
        if (x < 0x80) {
            pk_byte(p, (byte)x);
        } else if (x < 0x100) {
            pk_hdr(p, 0xcc, (uint32_t)x, 1, 0);
        } else if (x < 0x10000) {
            pk_hdr(p, 0xcd, (uint32_t)x, 2, 0);
        } else if (x <= 0xffffffff) {
            pk_hdr(p, 0xce, (uint32_t)x, 4, 0);
        } else {
            pk_hdr64(p, 0xcf, (uint64_t)x);
        }
    } else {
        if (x >= -32) {
            pk_byte(p, (byte)x);
        } else if (x >= -128) {
            pk_hdr(p, 0xd0, (uint32_t)x, 1, 0);
        } else if (x >= -32768) {
            pk_hdr(p, 0xd1, (uint32_t)x, 2, 0);
        } else if (x >= -2147483647 - 1) {
            pk_hdr(p, 0xd2, (uint32_t)x, 4, 0);
        } else {
            pk_hdr64(p, 0xd3, (uint64_t)x);
        }
    }
}

// An int object that is not a small int.
static void pk_bigint(packer_t *p, mp_obj_t o) {
    #if MICROPY_LONGINT_IMPL == MICROPY_LONGINT_IMPL_MPZ
    // Read the mpz digits directly. mp_obj_int_to_bytes_impl() with an
    // overflow check is not enough: it lets -2**64 through as 0.
    const mpz_t *z = &((mp_obj_int_t *)MP_OBJ_TO_PTR(o))->mpz;
    uint64_t mag = 0;
    for (size_t i = z->len; i--;) {
        if (mag >> (64 - MPZ_DIG_SIZE)) {
            raise_unsupported_msg(z->neg ? MP_ERROR_TEXT("huge signed int") : MP_ERROR_TEXT("huge unsigned int"));
        }
        mag = (mag << MPZ_DIG_SIZE) | z->dig[i];
    }
    if (z->neg) {
        if (mag > 0x8000000000000000ULL) {
            raise_unsupported_msg(MP_ERROR_TEXT("huge signed int"));
        }
        pk_int64(p, (int64_t)(0 - mag)); // mag == 2**63 gives INT64_MIN
    } else if (mag < 0x8000000000000000ULL) {
        pk_int64(p, (int64_t)mag);
    } else {
        pk_hdr64(p, 0xcf, mag);
    }
    #elif MICROPY_LONGINT_IMPL == MICROPY_LONGINT_IMPL_LONGLONG
    pk_int64(p, ((mp_obj_int_t *)MP_OBJ_TO_PTR(o))->val);
    #else
    (void)o;
    pk_int64(p, mp_obj_get_int(o));
    #endif
}

#if MICROPY_PY_BUILTINS_FLOAT
static void pk_float(packer_t *p, mp_float_t f) {
    if (p->fprec == FPREC_DOUBLE) {
        double d = (double)f;
        uint64_t u;
        memcpy(&u, &d, sizeof(u));
        pk_hdr64(p, 0xcb, u);
    } else if (p->fprec == FPREC_SINGLE) {
        float s = (float)f;
        uint32_t u;
        memcpy(&u, &s, sizeof(u));
        pk_hdr(p, 0xca, u, 4, 0);
    } else {
        mp_raise_ValueError(MP_ERROR_TEXT("invalid float precision"));
    }
}
#endif

static void pk_str(packer_t *p, const byte *s, size_t len) {
    byte *b;
    if (len < 32) {
        b = pk_reserve(p, 1 + len);
        *b++ = 0xa0 | (byte)len;
    } else if (len < 0x100) {
        b = pk_hdr(p, 0xd9, len, 1, len);
    } else if (len < 0x10000) {
        b = pk_hdr(p, 0xda, len, 2, len);
    } else if (!len_exceeds_u32(len)) {
        b = pk_hdr(p, 0xdb, len, 4, len);
    } else {
        raise_unsupported_msg(MP_ERROR_TEXT("huge string"));
    }
    memcpy(b, s, len);
}

static void pk_bin(packer_t *p, mp_obj_t o) {
    mp_buffer_info_t bi;
    mp_get_buffer_raise(o, &bi, MP_BUFFER_READ);
    byte *b;
    if (bi.len < 0x100) {
        b = pk_hdr(p, 0xc4, bi.len, 1, bi.len);
    } else if (bi.len < 0x10000) {
        b = pk_hdr(p, 0xc5, bi.len, 2, bi.len);
    } else if (!len_exceeds_u32(bi.len)) {
        b = pk_hdr(p, 0xc6, bi.len, 4, bi.len);
    } else {
        raise_unsupported_msg(MP_ERROR_TEXT("huge binary string"));
    }
    memcpy(b, bi.buf, bi.len);
}

// Array (fix_base 0x90) and map (0x80) headers. umsgpack says "huge array"
// for both, and so do we.
static void pk_container_hdr(packer_t *p, size_t len, byte fix_base, byte tag16) {
    if (len < 16) {
        pk_byte(p, fix_base | (byte)len);
    } else if (len < 0x10000) {
        pk_hdr(p, tag16, len, 2, 0);
    } else if (!len_exceeds_u32(len)) {
        pk_hdr(p, tag16 + 1, len, 4, 0);
    } else {
        raise_unsupported_msg(MP_ERROR_TEXT("huge array"));
    }
}

static void pk_enter(packer_t *p) {
    MP_STACK_CHECK();
    if (++p->depth > MSGPACKC_MAX_DEPTH) {
        raise_depth();
    }
}

static void pk_tuple(packer_t *p, mp_obj_tuple_t *t) {
    pk_container_hdr(p, t->len, 0x90, 0xdc);
    pk_enter(p);
    for (size_t i = 0; i < t->len; i++) {
        pk_obj(p, t->items[i]);
    }
    p->depth--;
}

// The list may change under us only if an ext packer (Python code) changes it.
// Items are re-read on every iteration and a size change is an error: the
// header already written would no longer match.
static void pk_list(packer_t *p, mp_obj_list_t *l) {
    size_t n = l->len;
    pk_container_hdr(p, n, 0x90, 0xdc);
    pk_enter(p);
    for (size_t i = 0; i < n; i++) {
        if (l->len != n) {
            raise_changed();
        }
        pk_obj(p, l->items[i]);
    }
    if (l->len != n) {
        raise_changed();
    }
    p->depth--;
}

// Same order as `for k, v in d.items()`: the slots of the table in order.
static void pk_map(packer_t *p, mp_obj_t d) {
    mp_map_t *map = mp_obj_dict_get_map(d);
    size_t n = map->used;
    pk_container_hdr(p, n, 0x80, 0xde);
    pk_enter(p);
    size_t done = 0;
    for (size_t i = 0; i < map->alloc; i++) {
        if (mp_map_slot_is_filled(map, i)) {
            if (done++ == n) {
                raise_changed();
            }
            mp_obj_t value = map->table[i].value;
            pk_obj(p, map->table[i].key);
            pk_obj(p, value);
        }
    }
    if (done != n || map->used != n) {
        raise_changed();
    }
    p->depth--;
}

// Ext header followed by the bytes returned by a packb() method.
static void pk_ext(packer_t *p, mp_obj_t ext_type, mp_obj_t data) {
    byte type = (byte)mp_obj_get_int(ext_type);
    mp_buffer_info_t bi;
    mp_get_buffer_raise(data, &bi, MP_BUFFER_READ);
    size_t len = bi.len;
    byte *b;
    if (len == 1 || len == 2 || len == 4 || len == 8 || len == 16) {
        static const byte fixext[17] = {
            [1] = 0xd4, [2] = 0xd5, [4] = 0xd6, [8] = 0xd7, [16] = 0xd8,
        };
        b = pk_reserve(p, 2 + len);
        b[0] = fixext[len];
        b[1] = type;
        b += 2;
    } else if (len < 0x100) {
        b = pk_hdr(p, 0xc7, len, 1, 1 + len);
        *b++ = type;
    } else if (len < 0x10000) {
        b = pk_hdr(p, 0xc8, len, 2, 1 + len);
        *b++ = type;
    } else if (!len_exceeds_u32(len)) {
        b = pk_hdr(p, 0xc9, len, 4, 1 + len);
        *b++ = type;
    } else {
        raise_unsupported_msg(MP_ERROR_TEXT("huge ext data"));
    }
    memcpy(b, bi.buf, len);
}

static inline bool is_instance(mp_obj_t o, mp_obj_t type) {
    return mp_obj_is_subclass_fast(MP_OBJ_FROM_PTR(mp_obj_get_type(o)), type);
}

// A registered built-in type (e.g. complex, set, tuple) has priority over the
// native encodings, as in umsgpack. Returns false if o has no ext packer.
static bool pk_builtin_ext(packer_t *p, mp_obj_t o) {
    mp_map_t *map = p->builtins;
    for (size_t i = 0; i < map->alloc; i++) {
        if (!mp_map_slot_is_filled(map, i) || !is_instance(o, map->table[i].key)) {
            continue;
        }
        // value is (packer class, ext_type)
        size_t n;
        mp_obj_t *pair;
        mp_obj_tuple_get(map->table[i].value, &n, &pair);
        mp_obj_t ext_type = pair[1];
        mp_obj_t dest[4];
        mp_load_method_maybe(pair[0], MP_QSTR_packb, dest);
        if (dest[0] == MP_OBJ_NULL) {
            raise_with_obj(&mp_type_NotImplementedError, "Class ",
                MP_OBJ_FROM_PTR(mp_obj_get_type(o)), PRINT_REPR, " invalid packb()");
        }
        dest[2] = o;
        dest[3] = options_dict(&p->options, p->kw);
        pk_ext(p, ext_type, mp_call_method_n_kw(2, 0, dest));
        return true;
    }
    return false;
}

// Last chance: an instance of a class registered with @ext_serializable(n).
static void pk_custom_ext(packer_t *p, mp_obj_t o) {
    mp_map_t *map = p->custom;
    for (size_t i = 0; map != NULL && i < map->alloc; i++) {
        if (!mp_map_slot_is_filled(map, i) || !is_instance(o, map->table[i].key)) {
            continue;
        }
        mp_obj_t ext_type = map->table[i].value;
        mp_obj_t dest[2];
        mp_load_method_maybe(o, MP_QSTR_packb, dest);
        if (dest[0] == MP_OBJ_NULL) {
            break;
        }
        pk_ext(p, ext_type, mp_call_method_n_kw(0, 0, dest));
        return;
    }
    raise_unsupported_type(o);
}

// Instances of subclasses of the native types (and native subtypes such as
// namedtuple), in the order umsgpack tests them with isinstance().
static void pk_subclass(packer_t *p, mp_obj_t o, const mp_obj_type_t *type) {
    static const mp_obj_type_t *const natives[] = {
        &mp_type_int,
        #if MICROPY_PY_BUILTINS_FLOAT
        &mp_type_float,
        #endif
        &mp_type_str, &mp_type_bytes,
        #if MICROPY_PY_BUILTINS_BYTEARRAY
        &mp_type_bytearray,
        #endif
        &mp_type_list, &mp_type_tuple, &mp_type_dict,
    };
    for (size_t i = 0; i < MP_ARRAY_SIZE(natives); i++) {
        if (!mp_obj_is_subclass_fast(MP_OBJ_FROM_PTR(type), MP_OBJ_FROM_PTR(natives[i]))) {
            continue;
        }
        if (mp_obj_is_instance_type(type)) {
            // A Python subclass: pack the native object it wraps.
            pk_obj(p, mp_obj_cast_to_native_base(o, MP_OBJ_FROM_PTR(natives[i])));
            return;
        }
        if (natives[i] == &mp_type_tuple) {
            // A native subtype with the tuple layout (namedtuple).
            pk_tuple(p, MP_OBJ_TO_PTR(o));
            return;
        }
        // Other native subtypes have an unknown layout: not packed natively.
        break;
    }
    pk_custom_ext(p, o);
}

static void pk_obj(packer_t *p, mp_obj_t o) {
    if (o == mp_const_none) {
        pk_byte(p, 0xc0);
        return;
    }
    if (p->builtins != NULL && pk_builtin_ext(p, o)) {
        return;
    }
    if (mp_obj_is_small_int(o)) {
        pk_int64(p, MP_OBJ_SMALL_INT_VALUE(o));
    } else if (mp_obj_is_qstr(o)) {
        size_t len;
        const byte *s = qstr_data(MP_OBJ_QSTR_VALUE(o), &len);
        pk_str(p, s, len);
    } else if (o == mp_const_false) {
        pk_byte(p, 0xc2);
    } else if (o == mp_const_true) {
        pk_byte(p, 0xc3);
        #if MICROPY_PY_BUILTINS_FLOAT
    } else if (mp_obj_is_float(o)) {
        pk_float(p, mp_obj_float_get(o));
        #endif
    } else {
        const mp_obj_type_t *type = mp_obj_get_type(o);
        if (type == &mp_type_str) {
            GET_STR_DATA_LEN(o, s, len);
            pk_str(p, s, len);
        } else if (type == &mp_type_dict
                   #if MICROPY_PY_COLLECTIONS_ORDEREDDICT
                   || type == &mp_type_ordereddict
                   #endif
                   ) {
            pk_map(p, o);
        } else if (type == &mp_type_list) {
            pk_list(p, MP_OBJ_TO_PTR(o));
        } else if (type == &mp_type_tuple) {
            pk_tuple(p, MP_OBJ_TO_PTR(o));
        } else if (type == &mp_type_int) {
            pk_bigint(p, o);
        } else if (type == &mp_type_bytes
                   #if MICROPY_PY_BUILTINS_BYTEARRAY
                   || type == &mp_type_bytearray
                   #endif
                   ) {
            pk_bin(p, o);
        } else {
            pk_subclass(p, o, type);
        }
    }
}

static void packer_init(packer_t *p, mp_map_t *kw) {
    vstr_init(&p->vstr, 64);
    p->kw = kw;
    p->options = MP_OBJ_NULL;
    p->depth = 0;
    p->fprec = FPREC_NATIVE;
    mp_obj_t prec = kw_get(kw, MP_QSTR_force_float_precision);
    if (prec != MP_OBJ_NULL) {
        if (mp_obj_equal(prec, MP_OBJ_NEW_QSTR(MP_QSTR_double))) {
            p->fprec = FPREC_DOUBLE;
        } else if (mp_obj_equal(prec, MP_OBJ_NEW_QSTR(MP_QSTR_single))) {
            p->fprec = FPREC_SINGLE;
        } else {
            // Like umsgpack, only an error if a float is actually packed.
            p->fprec = FPREC_INVALID;
        }
    }
    p->builtins = ext_map(MP_QSTR_builtins);
    p->custom = ext_map(MP_QSTR_custom);
}

// dumps(obj, **options) -> bytes
static mp_obj_t msgpackc_dumps(size_t n_args, const mp_obj_t *args, mp_map_t *kw) {
    mp_arg_check_num(n_args, kw->used, 1, 1, true);
    packer_t p;
    packer_init(&p, kw);
    pk_obj(&p, args[0]);
    return mp_obj_new_bytes_from_vstr(&p.vstr);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(msgpackc_dumps_obj, 1, msgpackc_dumps);

// Look up fp.<meth> into dest. If it is the generic C stream method, fp is a
// native stream: return its protocol so data can be moved without method
// calls. Otherwise (Python file-like objects) return NULL and use dest.
// The protocol slot alone is not enough: other types use it for other
// protocols (machine.Pin, for instance).
static const mp_stream_p_t *native_stream(mp_obj_t fp, qstr meth, const void *generic, mp_obj_t *dest) {
    mp_load_method(fp, meth, dest);
    if (dest[0] == MP_OBJ_FROM_PTR(generic)) {
        return MP_OBJ_TYPE_GET_SLOT_OR_NULL(mp_obj_get_type(fp), protocol);
    }
    return NULL;
}

// dump(obj, fp, **options): pack, then write everything with a single write.
static mp_obj_t msgpackc_dump(size_t n_args, const mp_obj_t *args, mp_map_t *kw) {
    mp_arg_check_num(n_args, kw->used, 2, 2, true);
    packer_t p;
    packer_init(&p, kw);
    pk_obj(&p, args[0]);
    mp_obj_t fp = args[1];
    mp_obj_t dest[3];
    const mp_stream_p_t *sp = native_stream(fp, MP_QSTR_write, &mp_stream_write_obj, dest);
    if (sp != NULL && sp->write != NULL) {
        int err;
        mp_uint_t n = mp_stream_rw(fp, p.vstr.buf, p.vstr.len, &err, MP_STREAM_RW_WRITE);
        if (err != 0) {
            mp_raise_OSError(err);
        }
        if (n != p.vstr.len) {
            mp_raise_OSError(MP_EIO);
        }
        vstr_clear(&p.vstr);
    } else {
        dest[2] = mp_obj_new_bytes_from_vstr(&p.vstr);
        mp_call_method_n_kw(1, 0, dest);
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_KW(msgpackc_dump_obj, 2, msgpackc_dump);

/******************************************************************************/
// Unpacking

typedef struct _unpacker_t {
    // Buffer mode: [cur, end) is the data still to decode.
    const byte *cur;
    const byte *end;
    // Set for a mutable source (bytearray, memoryview): Python code run by an
    // ext unpackb() could resize it, so the pointers are re-validated after.
    mp_obj_t src;
    const byte *base;
    // Stream mode (load): stream != MP_OBJ_NULL.
    mp_obj_t stream;
    const mp_stream_p_t *sp; // NULL: use the read method instead
    mp_obj_t read_meth[3];
    mp_map_t *packers;       // registered ext types, NULL if none
    mp_map_t *kw;            // **options, for the ext unpackb methods
    mp_obj_t options;
    uint16_t depth;
    bool use_tuple;
    bool use_ordered_dict;
    bool allow_invalid_utf8;
    bool key; // the object being decoded is a map key
    byte hdr[8];
} unpacker_t;

static mp_obj_t up_obj(unpacker_t *u);

static void up_stream_read(unpacker_t *u, byte *buf, size_t n) {
    if (u->sp != NULL) {
        int err;
        mp_uint_t got = mp_stream_rw(u->stream, buf, n, &err, MP_STREAM_RW_READ);
        if (err != 0) {
            mp_raise_OSError(err);
        }
        if (got != n) {
            raise_insufficient();
        }
        return;
    }
    // Any object with a read(n) method, called until it has supplied n bytes.
    while (n > 0) {
        u->read_meth[2] = MP_OBJ_NEW_SMALL_INT(n);
        mp_obj_t data = mp_call_method_n_kw(1, 0, u->read_meth);
        if (data == mp_const_none) {
            raise_insufficient();
        }
        mp_buffer_info_t bi;
        mp_get_buffer_raise(data, &bi, MP_BUFFER_READ);
        if (bi.len == 0) {
            raise_insufficient();
        }
        if (bi.len > n) {
            mp_raise_ValueError(MP_ERROR_TEXT("read() returned too much data"));
        }
        memcpy(buf, bi.buf, bi.len);
        buf += bi.len;
        n -= bi.len;
    }
}

// n (<= 8) header bytes.
static inline const byte *up_read(unpacker_t *u, size_t n) {
    if (u->stream == MP_OBJ_NULL) {
        if ((size_t)(u->end - u->cur) < n) {
            raise_insufficient();
        }
        const byte *b = u->cur;
        u->cur += n;
        return b;
    }
    up_stream_read(u, u->hdr, n);
    return u->hdr;
}

static uint32_t up_be(unpacker_t *u, size_t n) {
    const byte *b = up_read(u, n);
    uint32_t x = 0;
    while (n--) {
        x = (x << 8) | *b++;
    }
    return x;
}

static uint64_t up_be64(unpacker_t *u) {
    const byte *b = up_read(u, 8);
    uint64_t x = 0;
    for (size_t i = 0; i < 8; i++) {
        x = (x << 8) | b[i];
    }
    return x;
}

// n payload bytes. Buffer mode: a pointer into the input. Stream mode: read
// into *vstr (initialised here), growing it as data arrives so a corrupt length
// cannot allocate more memory than the stream really delivers.
static const byte *up_payload(unpacker_t *u, size_t n, vstr_t *vstr) {
    if (u->stream == MP_OBJ_NULL) {
        if ((size_t)(u->end - u->cur) < n) {
            raise_insufficient();
        }
        const byte *b = u->cur;
        u->cur += n;
        return b;
    }
    vstr_init(vstr, n < 256 ? n : 256);
    while (vstr->len < n) {
        size_t chunk = n - vstr->len;
        size_t limit = vstr->len < 256 ? 256 : vstr->len;
        if (chunk > limit) {
            chunk = limit;
        }
        byte *b = (byte *)vstr_add_len(vstr, chunk);
        up_stream_read(u, b, chunk);
    }
    return (const byte *)vstr->buf;
}

static mp_obj_t up_new_bytes(unpacker_t *u, const byte *b, size_t n, vstr_t *vstr) {
    if (u->stream == MP_OBJ_NULL) {
        return mp_obj_new_bytes(b, n);
    }
    return mp_obj_new_bytes_from_vstr(vstr);
}

static mp_obj_t up_bin(unpacker_t *u, size_t n) {
    vstr_t vstr;
    const byte *b = up_payload(u, n, &vstr);
    return up_new_bytes(u, b, n, &vstr);
}

static mp_obj_t up_str(unpacker_t *u, size_t n, bool key) {
    vstr_t vstr;
    const byte *s = up_payload(u, n, &vstr);
    #if MICROPY_PY_BUILTINS_STR_UNICODE && MICROPY_PY_BUILTINS_STR_UNICODE_CHECK
    if (!unicode_encoding_check(MP_ENCODING_UTF8, s, n)) {
        if (u->allow_invalid_utf8) {
            return up_new_bytes(u, s, n, &vstr);
        }
        mp_raise_msg(&mp_type_msgpackc_InvalidStringException, MP_ERROR_TEXT("unpacked string is invalid utf-8"));
    }
    #endif
    #if MSGPACKC_REUSE_QSTR
    // A key that is an existing qstr: no allocation, and dict lookups compare
    // qstrs. New qstrs are never created from input data.
    qstr q = key ? qstr_find_strn((const char *)s, n) : MP_QSTRnull;
    if (q != MP_QSTRnull) {
        if (u->stream != MP_OBJ_NULL) {
            vstr_clear(&vstr);
        }
        return MP_OBJ_NEW_QSTR(q);
    }
    #else
    (void)key;
    #endif
    if (u->stream != MP_OBJ_NULL) {
        return mp_obj_new_str_from_vstr(&vstr);
    }
    return mp_obj_new_str_copy(&mp_type_str, s, n);
}

// Python code (an ext unpackb, a __hash__ or __eq__ of a key) has run: if the
// source buffer is mutable it may have been resized or moved.
static void up_revalidate(unpacker_t *u) {
    if (u->src == MP_OBJ_NULL) {
        return;
    }
    mp_buffer_info_t bi;
    mp_get_buffer_raise(u->src, &bi, MP_BUFFER_READ);
    size_t cur = u->cur - u->base;
    size_t end = u->end - u->base;
    if (bi.len < end) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("buffer changed during unpacking"));
    }
    u->base = bi.buf;
    u->cur = u->base + cur;
    u->end = u->base + end;
}

static mp_obj_t up_ext(unpacker_t *u, size_t n) {
    mp_int_t ext_type = (int8_t)up_read(u, 1)[0];
    mp_obj_t data = up_bin(u, n);
    mp_map_elem_t *e = NULL;
    if (u->packers != NULL) {
        e = mp_map_lookup(u->packers, MP_OBJ_NEW_SMALL_INT(ext_type), MP_MAP_LOOKUP);
    }
    if (e == NULL) {
        // Same text as umsgpack's f"ext_type: 0x{ext_type:0X}"
        if (ext_type < 0) {
            mp_raise_msg_varg(&mp_type_msgpackc_UnsupportedTypeException,
                MP_ERROR_TEXT("ext_type: 0x-%X"), (unsigned int)-ext_type);
        }
        mp_raise_msg_varg(&mp_type_msgpackc_UnsupportedTypeException,
            MP_ERROR_TEXT("ext_type: 0x%X"), (unsigned int)ext_type);
    }
    mp_obj_t cls = e->value;
    mp_obj_t dest[4];
    mp_load_method_maybe(cls, MP_QSTR_unpackb, dest);
    if (dest[0] == MP_OBJ_NULL) {
        raise_with_obj(&mp_type_NotImplementedError, "Ext class ", cls, PRINT_REPR, " lacks unpackb()");
    }
    dest[2] = data;
    dest[3] = options_dict(&u->options, u->kw);
    mp_obj_t obj = mp_call_method_n_kw(2, 0, dest);
    up_revalidate(u);
    return obj;
}

static void up_enter(unpacker_t *u) {
    MP_STACK_CHECK();
    if (++u->depth > MSGPACKC_MAX_DEPTH) {
        raise_depth();
    }
}

// How many items can be preallocated for a container announcing n of them.
// Each item takes at least one byte, so in buffer mode a larger n cannot be
// genuine: allocate only what the data could hold and fail when it runs out.
static size_t up_prealloc(unpacker_t *u, size_t n) {
    size_t limit = u->stream == MP_OBJ_NULL ? (size_t)(u->end - u->cur) : 64;
    return n < limit ? n : limit;
}

static mp_obj_t up_array(unpacker_t *u, size_t n) {
    up_enter(u);
    mp_obj_t res;
    if (up_prealloc(u, n) == n) {
        // The usual case: items go straight into a list or tuple of size n.
        mp_obj_t *items;
        if (u->use_tuple) {
            res = mp_obj_new_tuple(n, NULL);
            items = ((mp_obj_tuple_t *)MP_OBJ_TO_PTR(res))->items;
        } else {
            res = mp_obj_new_list(n, NULL);
            items = ((mp_obj_list_t *)MP_OBJ_TO_PTR(res))->items;
        }
        for (size_t i = 0; i < n; i++) {
            items[i] = up_obj(u);
        }
    } else {
        res = mp_obj_new_list(0, NULL);
        for (size_t i = 0; i < n; i++) {
            mp_obj_list_append(res, up_obj(u));
        }
        if (u->use_tuple) {
            mp_obj_list_t *l = MP_OBJ_TO_PTR(res);
            res = mp_obj_new_tuple(l->len, l->items);
        }
    }
    u->depth--;
    return res;
}

// A list used as a map key becomes a tuple, recursively (umsgpack's
// _deep_list_to_tuple).
static mp_obj_t list_to_tuple(mp_obj_t o) {
    if (!mp_obj_is_type(o, &mp_type_list)) {
        return o;
    }
    MP_STACK_CHECK();
    mp_obj_list_t *l = MP_OBJ_TO_PTR(o);
    mp_obj_tuple_t *t = MP_OBJ_TO_PTR(mp_obj_new_tuple(l->len, NULL));
    for (size_t i = 0; i < l->len; i++) {
        t->items[i] = list_to_tuple(l->items[i]);
    }
    return MP_OBJ_FROM_PTR(t);
}

static bool key_is_simple(mp_obj_t k) {
    return mp_obj_is_small_int(k) || mp_obj_is_qstr(k) || mp_obj_is_float(k)
           || k == mp_const_none || k == mp_const_true || k == mp_const_false
           || mp_obj_is_exact_type(k, &mp_type_str) || mp_obj_is_exact_type(k, &mp_type_bytes)
           || mp_obj_is_exact_type(k, &mp_type_int);
}

static void up_check_hashable(unpacker_t *u, mp_obj_t k) {
    if (key_is_simple(k)) {
        return;
    }
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_unary_op(MP_UNARY_OP_HASH, k);
        nlr_pop();
    } else {
        raise_with_obj(&mp_type_msgpackc_UnhashableKeyException, "\"", k, PRINT_STR, "\"");
    }
    up_revalidate(u);
}

static mp_obj_t up_map(unpacker_t *u, size_t n) {
    up_enter(u);
    mp_obj_t d = mp_obj_new_dict(up_prealloc(u, n));
    #if MICROPY_PY_COLLECTIONS_ORDEREDDICT
    if (u->use_ordered_dict) {
        mp_obj_dict_t *od = MP_OBJ_TO_PTR(d);
        od->base.type = &mp_type_ordereddict;
        od->map.is_ordered = 1;
    }
    #else
    if (u->use_ordered_dict) {
        mp_raise_NotImplementedError(MP_ERROR_TEXT("OrderedDict not available"));
    }
    #endif
    mp_map_t *map = mp_obj_dict_get_map(d);
    for (size_t i = 0; i < n; i++) {
        u->key = true;
        mp_obj_t k = list_to_tuple(up_obj(u));
        up_check_hashable(u, k);
        // A single lookup both detects a duplicate and reserves the slot. The
        // slot stays valid while the value is decoded: nothing else can reach
        // this dict until it is returned.
        mp_map_elem_t *e = mp_map_lookup(map, k, MP_MAP_LOOKUP_ADD_IF_NOT_FOUND);
        if (!key_is_simple(k)) {
            up_revalidate(u);
        }
        if (e->value != MP_OBJ_NULL) {
            vstr_t vstr;
            mp_print_t print;
            vstr_init_print(&vstr, 32, &print);
            mp_print_str(&print, "\"");
            mp_obj_print_helper(&print, k, PRINT_STR);
            mp_print_str(&print, "\" (");
            mp_obj_print_helper(&print, MP_OBJ_FROM_PTR(mp_obj_get_type(k)), PRINT_STR);
            mp_print_str(&print, ")");
            nlr_raise(mp_obj_new_exception_arg1(&mp_type_msgpackc_DuplicateKeyException,
                mp_obj_new_str_from_vstr(&vstr)));
        }
        e->value = up_obj(u);
    }
    u->depth--;
    return d;
}

static mp_obj_t up_float32(unpacker_t *u) {
    #if MICROPY_PY_BUILTINS_FLOAT
    uint32_t x = up_be(u, 4);
    float f;
    memcpy(&f, &x, sizeof(f));
    return mp_obj_new_float_from_f(f);
    #else
    (void)u;
    raise_unsupported_msg(MP_ERROR_TEXT("float not supported"));
    #endif
}

static mp_obj_t up_float64(unpacker_t *u) {
    #if MICROPY_PY_BUILTINS_FLOAT
    uint64_t x = up_be64(u);
    double d;
    memcpy(&d, &x, sizeof(d));
    return mp_obj_new_float_from_d(d);
    #else
    (void)u;
    raise_unsupported_msg(MP_ERROR_TEXT("float not supported"));
    #endif
}

static mp_obj_t up_obj(unpacker_t *u) {
    bool key = u->key; // only for this object, not for what it contains
    u->key = false;
    byte ic = up_read(u, 1)[0];
    if (ic <= 0x7f) {
        return MP_OBJ_NEW_SMALL_INT(ic);
    }
    if (ic >= 0xe0) {
        return MP_OBJ_NEW_SMALL_INT((int8_t)ic);
    }
    if (ic <= 0x8f) {
        return up_map(u, ic & 0x0f);
    }
    if (ic <= 0x9f) {
        return up_array(u, ic & 0x0f);
    }
    if (ic <= 0xbf) {
        return up_str(u, ic & 0x1f, key);
    }
    switch (ic) {
        case 0xc0:
            return mp_const_none;
        case 0xc1:
            mp_raise_msg(&mp_type_msgpackc_ReservedCodeException, MP_ERROR_TEXT("got 0xc1"));
        case 0xc2:
            return mp_const_false;
        case 0xc3:
            return mp_const_true;
        case 0xc4:
            return up_bin(u, up_be(u, 1));
        case 0xc5:
            return up_bin(u, up_be(u, 2));
        case 0xc6:
            return up_bin(u, up_be(u, 4));
        case 0xc7:
            return up_ext(u, up_be(u, 1));
        case 0xc8:
            return up_ext(u, up_be(u, 2));
        case 0xc9:
            return up_ext(u, up_be(u, 4));
        case 0xca:
            return up_float32(u);
        case 0xcb:
            return up_float64(u);
        case 0xcc:
            return MP_OBJ_NEW_SMALL_INT(up_be(u, 1));
        case 0xcd:
            return MP_OBJ_NEW_SMALL_INT(up_be(u, 2));
        case 0xce:
            return mp_obj_new_int_from_uint(up_be(u, 4));
        case 0xcf:
            return mp_obj_new_int_from_ull(up_be64(u));
        case 0xd0:
            return MP_OBJ_NEW_SMALL_INT((int8_t)up_be(u, 1));
        case 0xd1:
            return MP_OBJ_NEW_SMALL_INT((int16_t)up_be(u, 2));
        case 0xd2:
            return mp_obj_new_int((int32_t)up_be(u, 4));
        case 0xd3:
            return mp_obj_new_int_from_ll((int64_t)up_be64(u));
        case 0xd4:
            return up_ext(u, 1);
        case 0xd5:
            return up_ext(u, 2);
        case 0xd6:
            return up_ext(u, 4);
        case 0xd7:
            return up_ext(u, 8);
        case 0xd8:
            return up_ext(u, 16);
        case 0xd9:
            return up_str(u, up_be(u, 1), key);
        case 0xda:
            return up_str(u, up_be(u, 2), key);
        case 0xdb:
            return up_str(u, up_be(u, 4), key);
        case 0xdc:
            return up_array(u, up_be(u, 2));
        case 0xdd:
            return up_array(u, up_be(u, 4));
        case 0xde:
            return up_map(u, up_be(u, 2));
        default: // 0xdf
            return up_map(u, up_be(u, 4));
    }
}

static void unpacker_init(unpacker_t *u, mp_map_t *kw) {
    u->src = MP_OBJ_NULL;
    u->stream = MP_OBJ_NULL;
    u->sp = NULL;
    u->kw = kw;
    u->options = MP_OBJ_NULL;
    u->depth = 0;
    u->key = false;
    u->use_tuple = kw_flag(kw, MP_QSTR_use_tuple);
    u->use_ordered_dict = kw_flag(kw, MP_QSTR_use_ordered_dict);
    u->allow_invalid_utf8 = kw_flag(kw, MP_QSTR_allow_invalid_utf8);
    u->packers = ext_map(MP_QSTR_packers);
}

static void unpacker_set_buffer(unpacker_t *u, mp_obj_t src, const byte *buf, size_t len) {
    u->base = buf;
    u->cur = buf;
    u->end = buf + len;
    // bytes are immutable: no need to re-validate the buffer after callbacks.
    u->src = mp_obj_is_type(src, &mp_type_bytes) ? MP_OBJ_NULL : src;
}

// loads(data, **options): data is bytes, bytearray or any other read buffer
// except str. Trailing bytes after the first object are ignored (as umsgpack).
static mp_obj_t msgpackc_loads(size_t n_args, const mp_obj_t *args, mp_map_t *kw) {
    mp_arg_check_num(n_args, kw->used, 1, 1, true);
    mp_buffer_info_t bi;
    if (mp_obj_is_str(args[0]) || !mp_get_buffer(args[0], &bi, MP_BUFFER_READ)) {
        mp_raise_TypeError(MP_ERROR_TEXT("Need 'bytes' or 'bytearray'"));
    }
    unpacker_t u;
    unpacker_init(&u, kw);
    unpacker_set_buffer(&u, args[0], bi.buf, bi.len);
    return up_obj(&u);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(msgpackc_loads_obj, 1, msgpackc_loads);

// load(fp, **options): reads exactly the bytes of one object from fp.
static mp_obj_t msgpackc_load(size_t n_args, const mp_obj_t *args, mp_map_t *kw) {
    mp_arg_check_num(n_args, kw->used, 1, 1, true);
    unpacker_t u;
    unpacker_init(&u, kw);
    u.stream = args[0];
    u.sp = native_stream(u.stream, MP_QSTR_read, &mp_stream_read_obj, u.read_meth);
    if (u.sp != NULL && u.sp->read == NULL) {
        u.sp = NULL;
    }
    return up_obj(&u);
}
static MP_DEFINE_CONST_FUN_OBJ_KW(msgpackc_load_obj, 1, msgpackc_load);

/******************************************************************************/
// Unpacker: incremental decoding of a byte stream fed in arbitrary chunks.

// Size of the first complete object in buf, or 0 if more data is needed.
// Iterative and allocation free: it only walks the headers, counting the
// items still expected, so deep nesting costs no stack. Returns SIZE_MAX for
// the reserved code 0xc1.
static size_t msgpack_measure(const byte *buf, size_t len) {
    const byte *p = buf;
    const byte *end = buf + len;
    uint64_t pending = 1;
    while (pending > 0) {
        if (p == end) {
            return 0;
        }
        byte ic = *p++;
        pending--;
        size_t hdr = 0;           // bytes of the length field
        uint64_t payload = 0;     // bytes after it
        uint64_t items = 0;       // children still to read
        size_t fixed = 0;         // fixed-size payload
        if (ic <= 0x7f || ic >= 0xe0) {
            continue;
        } else if (ic <= 0x8f) {
            items = 2 * (ic & 0x0f);
        } else if (ic <= 0x9f) {
            items = ic & 0x0f;
        } else if (ic <= 0xbf) {
            fixed = ic & 0x1f;
        } else {
            switch (ic) {
                case 0xc1:
                    return SIZE_MAX;
                case 0xc4:
                case 0xd9:
                    hdr = 1;
                    break;
                case 0xc5:
                case 0xda:
                    hdr = 2;
                    break;
                case 0xc6:
                case 0xdb:
                    hdr = 4;
                    break;
                case 0xc7:
                    hdr = 1;
                    fixed = 1;
                    break;
                case 0xc8:
                    hdr = 2;
                    fixed = 1;
                    break;
                case 0xc9:
                    hdr = 4;
                    fixed = 1;
                    break;
                case 0xca:
                case 0xce:
                case 0xd2:
                    fixed = 4;
                    break;
                case 0xcb:
                case 0xcf:
                case 0xd3:
                    fixed = 8;
                    break;
                case 0xcc:
                case 0xd0:
                    fixed = 1;
                    break;
                case 0xcd:
                case 0xd1:
                    fixed = 2;
                    break;
                case 0xd4:
                case 0xd5:
                case 0xd6:
                case 0xd7:
                case 0xd8:
                    fixed = 1 + ((size_t)1 << (ic - 0xd4));
                    break;
                case 0xdc:
                case 0xde:
                    hdr = 2;
                    break;
                case 0xdd:
                case 0xdf:
                    hdr = 4;
                    break;
                default: // 0xc0, 0xc2, 0xc3
                    break;
            }
        }
        if (hdr > 0) {
            if ((size_t)(end - p) < hdr) {
                return 0;
            }
            uint32_t n = 0;
            for (size_t i = 0; i < hdr; i++) {
                n = (n << 8) | *p++;
            }
            if (ic == 0xdc || ic == 0xdd) {
                items = n;
            } else if (ic == 0xde || ic == 0xdf) {
                items = 2 * (uint64_t)n;
            } else {
                payload = n;
            }
        }
        payload += fixed;
        if ((uint64_t)(end - p) < payload) {
            return 0;
        }
        p += payload;
        pending += items;
    }
    return p - buf;
}

typedef struct _mp_obj_unpacker_t {
    mp_obj_base_t base;
    vstr_t buf;            // fed data; [pos, buf.len) not consumed yet
    size_t pos;
    size_t max_buffer_size; // 0: unlimited
    size_t checked_len;     // pending bytes at the last incomplete measure
    mp_obj_t kw_dict;       // the load options (a dict)
    bool busy;              // decoding: feed() would move the buffer
} mp_obj_unpacker_t;

static mp_obj_t unpacker_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    mp_arg_check_num(n_args, n_kw, 0, 0, true);
    mp_obj_unpacker_t *self = mp_obj_malloc(mp_obj_unpacker_t, type);
    vstr_init(&self->buf, 64);
    self->pos = 0;
    self->max_buffer_size = 0;
    self->checked_len = SIZE_MAX;
    self->busy = false;
    // Keep the options as a dict: the map in args is only valid for this call.
    self->kw_dict = mp_obj_new_dict(n_kw);
    for (size_t i = 0; i < n_kw; i++) {
        mp_obj_t key = args[n_args + 2 * i];
        mp_obj_t value = args[n_args + 2 * i + 1];
        if (mp_obj_equal(key, MP_OBJ_NEW_QSTR(MP_QSTR_max_buffer_size))) {
            self->max_buffer_size = mp_obj_get_int(value);
        } else {
            mp_obj_dict_store(self->kw_dict, key, value);
        }
    }
    return MP_OBJ_FROM_PTR(self);
}

static void unpacker_check_idle(mp_obj_unpacker_t *self) {
    if (self->busy) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("Unpacker is busy"));
    }
}

// feed(data): append bytes to the internal buffer.
static mp_obj_t unpacker_feed(mp_obj_t self_in, mp_obj_t data) {
    mp_obj_unpacker_t *self = MP_OBJ_TO_PTR(self_in);
    unpacker_check_idle(self);
    mp_buffer_info_t bi;
    mp_get_buffer_raise(data, &bi, MP_BUFFER_READ);
    size_t pending = self->buf.len - self->pos;
    if (self->max_buffer_size != 0 && bi.len > self->max_buffer_size - pending) {
        mp_raise_ValueError(MP_ERROR_TEXT("Unpacker buffer full"));
    }
    if (self->pos > 0) {
        memmove(self->buf.buf, self->buf.buf + self->pos, pending);
        self->buf.len = pending;
        self->pos = 0;
    }
    vstr_add_strn(&self->buf, bi.buf, bi.len);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(unpacker_feed_obj, unpacker_feed);

// Size of the next complete object, 0 if there is none yet.
static size_t unpacker_next_size(mp_obj_unpacker_t *self) {
    size_t pending = self->buf.len - self->pos;
    if (pending == self->checked_len) {
        return 0; // nothing new since the last incomplete check
    }
    size_t n = msgpack_measure((const byte *)self->buf.buf + self->pos, pending);
    if (n == SIZE_MAX) {
        // Skip the bad byte so the stream can resynchronise.
        self->pos += 1;
        self->checked_len = SIZE_MAX;
        mp_raise_msg(&mp_type_msgpackc_ReservedCodeException, MP_ERROR_TEXT("got 0xc1"));
    }
    self->checked_len = n == 0 ? pending : SIZE_MAX;
    return n;
}

static mp_obj_t unpacker_iternext(mp_obj_t self_in) {
    mp_obj_unpacker_t *self = MP_OBJ_TO_PTR(self_in);
    unpacker_check_idle(self);
    size_t n = unpacker_next_size(self);
    if (n == 0) {
        return MP_OBJ_STOP_ITERATION;
    }
    const byte *start = (const byte *)self->buf.buf + self->pos;
    // Consume the object first: if decoding raises, the stream moves on.
    self->pos += n;
    unpacker_t u;
    unpacker_init(&u, mp_obj_dict_get_map(self->kw_dict));
    // No re-validation needed: feed() cannot move the buffer while busy.
    u.base = u.cur = start;
    u.end = start + n;
    self->busy = true;
    nlr_buf_t nlr;
    if (nlr_push(&nlr) == 0) {
        mp_obj_t obj = up_obj(&u);
        nlr_pop();
        self->busy = false;
        return obj;
    } else {
        self->busy = false;
        nlr_jump(nlr.ret_val);
    }
}

// next_raw(): the bytes of the next complete object, without decoding it, or
// None if no complete object has been fed yet.
static mp_obj_t unpacker_next_raw(mp_obj_t self_in) {
    mp_obj_unpacker_t *self = MP_OBJ_TO_PTR(self_in);
    unpacker_check_idle(self);
    size_t n = unpacker_next_size(self);
    if (n == 0) {
        return mp_const_none;
    }
    mp_obj_t raw = mp_obj_new_bytes((const byte *)self->buf.buf + self->pos, n);
    self->pos += n;
    return raw;
}
static MP_DEFINE_CONST_FUN_OBJ_1(unpacker_next_raw_obj, unpacker_next_raw);

// reset(): discard all buffered data.
static mp_obj_t unpacker_reset(mp_obj_t self_in) {
    mp_obj_unpacker_t *self = MP_OBJ_TO_PTR(self_in);
    unpacker_check_idle(self);
    self->buf.len = 0;
    self->pos = 0;
    self->checked_len = SIZE_MAX;
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(unpacker_reset_obj, unpacker_reset);

// len(unpacker): bytes buffered and not consumed yet.
static mp_obj_t unpacker_unary_op(mp_unary_op_t op, mp_obj_t self_in) {
    mp_obj_unpacker_t *self = MP_OBJ_TO_PTR(self_in);
    switch (op) {
        case MP_UNARY_OP_LEN:
            return MP_OBJ_NEW_SMALL_INT(self->buf.len - self->pos);
        case MP_UNARY_OP_BOOL:
            return mp_obj_new_bool(self->buf.len != self->pos);
        case MP_UNARY_OP_HASH:
            // As for any object without __hash__: its identity.
            return MP_OBJ_NEW_SMALL_INT((mp_uint_t)self_in);
        default:
            return MP_OBJ_NULL;
    }
}

static const mp_rom_map_elem_t unpacker_locals_dict_table[] = {
    { MP_ROM_QSTR(MP_QSTR_feed), MP_ROM_PTR(&unpacker_feed_obj) },
    { MP_ROM_QSTR(MP_QSTR_next_raw), MP_ROM_PTR(&unpacker_next_raw_obj) },
    { MP_ROM_QSTR(MP_QSTR_reset), MP_ROM_PTR(&unpacker_reset_obj) },
};
static MP_DEFINE_CONST_DICT(unpacker_locals_dict, unpacker_locals_dict_table);

static MP_DEFINE_CONST_OBJ_TYPE(
    msgpackc_unpacker_type,
    MP_QSTR_Unpacker,
    MP_TYPE_FLAG_ITER_IS_ITERNEXT,
    make_new, unpacker_make_new,
    iter, unpacker_iternext,
    unary_op, unpacker_unary_op,
    locals_dict, &unpacker_locals_dict
    );

/******************************************************************************/
// ext_serializable(ext_type, example=None): class decorator.

static mp_obj_t ext_register(size_t n_args, const mp_obj_t *args) {
    // args: ext_type, example (closed over by the decorator), cls
    mp_obj_t ext_type = args[0];
    mp_obj_t example = args[1];
    mp_obj_t cls = args[2];
    if (!mp_obj_is_int(ext_type)) {
        mp_raise_TypeError(MP_ERROR_TEXT("Ext type is not type integer"));
    }
    mp_int_t t = mp_obj_is_small_int(ext_type) ? MP_OBJ_SMALL_INT_VALUE(ext_type) : 1000;
    if (t < -128 || t > 127) {
        raise_with_obj(&mp_type_ValueError, "Ext type value ", ext_type, PRINT_STR,
            " is out of range of -128 to 127");
    }
    mp_obj_t reg = ext_registry(true);
    mp_obj_t packers = ext_dict(reg, MP_QSTR_packers);
    mp_obj_t custom = ext_dict(reg, MP_QSTR_custom);
    mp_map_elem_t *e = mp_map_lookup(mp_obj_dict_get_map(packers), ext_type, MP_MAP_LOOKUP);
    if (e != NULL) {
        vstr_t vstr;
        mp_print_t print;
        vstr_init_print(&vstr, 48, &print);
        mp_printf(&print, "Ext type %d already registered with class ", (int)t);
        mp_obj_print_helper(&print, e->value, PRINT_REPR);
        nlr_raise(mp_obj_new_exception_arg1(&mp_type_ValueError, mp_obj_new_str_from_vstr(&vstr)));
    }
    if (mp_map_lookup(mp_obj_dict_get_map(custom), cls, MP_MAP_LOOKUP) != NULL) {
        vstr_t vstr;
        mp_print_t print;
        vstr_init_print(&vstr, 48, &print);
        mp_print_str(&print, "Class ");
        mp_obj_print_helper(&print, cls, PRINT_REPR);
        mp_printf(&print, " already registered with Ext type %d", (int)t);
        nlr_raise(mp_obj_new_exception_arg1(&mp_type_ValueError, mp_obj_new_str_from_vstr(&vstr)));
    }
    mp_obj_dict_store(packers, ext_type, cls);
    if (example == mp_const_none) {
        mp_obj_dict_store(custom, cls, ext_type);
    } else {
        mp_obj_t pair[2] = { cls, ext_type };
        mp_obj_dict_store(ext_dict(reg, MP_QSTR_builtins), example, mp_obj_new_tuple(2, pair));
    }
    return cls;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(ext_register_obj, 3, 3, ext_register);

static mp_obj_t msgpackc_ext_serializable(size_t n_args, const mp_obj_t *args) {
    mp_obj_t closed[2] = { args[0], n_args > 1 ? args[1] : mp_const_none };
    return mp_obj_new_closure(MP_OBJ_FROM_PTR(&ext_register_obj), 2, closed);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(msgpackc_ext_serializable_obj, 1, 2, msgpackc_ext_serializable);

/******************************************************************************/
// Module

// Module attributes that are not constants: the registry dicts (as umsgpack
// exposes them) and ALoader, which is Python code in msgpackc_aio.py.
static mp_obj_t msgpackc___getattr__(mp_obj_t attr) {
    qstr name = mp_obj_str_get_qstr(attr);
    if (name == MP_QSTR_custom || name == MP_QSTR_builtins || name == MP_QSTR_packers) {
        return ext_dict(ext_registry(true), name);
    }
    if (name == MP_QSTR_ALoader) {
        mp_obj_t mod = mp_import_name(MP_QSTR_msgpackc_aio, mp_const_none, MP_OBJ_NEW_SMALL_INT(0));
        return mp_load_attr(mod, MP_QSTR_ALoader);
    }
    return MP_OBJ_NULL;
}
static MP_DEFINE_CONST_FUN_OBJ_1(msgpackc___getattr___obj, msgpackc___getattr__);

static MP_DEFINE_STR_OBJ(msgpackc_version_obj, "1.0.0");

static const mp_rom_map_elem_t msgpackc_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_msgpackc) },
    { MP_ROM_QSTR(MP_QSTR___version__), MP_ROM_PTR(&msgpackc_version_obj) },
    { MP_ROM_QSTR(MP_QSTR___getattr__), MP_ROM_PTR(&msgpackc___getattr___obj) },
    { MP_ROM_QSTR(MP_QSTR_dumps), MP_ROM_PTR(&msgpackc_dumps_obj) },
    { MP_ROM_QSTR(MP_QSTR_dump), MP_ROM_PTR(&msgpackc_dump_obj) },
    { MP_ROM_QSTR(MP_QSTR_loads), MP_ROM_PTR(&msgpackc_loads_obj) },
    { MP_ROM_QSTR(MP_QSTR_load), MP_ROM_PTR(&msgpackc_load_obj) },
    { MP_ROM_QSTR(MP_QSTR_Unpacker), MP_ROM_PTR(&msgpackc_unpacker_type) },
    { MP_ROM_QSTR(MP_QSTR_ext_serializable), MP_ROM_PTR(&msgpackc_ext_serializable_obj) },
    { MP_ROM_QSTR(MP_QSTR_float_precision), MP_ROM_QSTR(MSGPACKC_FLOAT_PRECISION) },
    { MP_ROM_QSTR(MP_QSTR_PackException), MP_ROM_PTR(&mp_type_msgpackc_PackException) },
    { MP_ROM_QSTR(MP_QSTR_UnpackException), MP_ROM_PTR(&mp_type_msgpackc_UnpackException) },
    { MP_ROM_QSTR(MP_QSTR_UnsupportedTypeException), MP_ROM_PTR(&mp_type_msgpackc_UnsupportedTypeException) },
    { MP_ROM_QSTR(MP_QSTR_InsufficientDataException), MP_ROM_PTR(&mp_type_msgpackc_InsufficientDataException) },
    { MP_ROM_QSTR(MP_QSTR_InvalidStringException), MP_ROM_PTR(&mp_type_msgpackc_InvalidStringException) },
    { MP_ROM_QSTR(MP_QSTR_ReservedCodeException), MP_ROM_PTR(&mp_type_msgpackc_ReservedCodeException) },
    { MP_ROM_QSTR(MP_QSTR_UnhashableKeyException), MP_ROM_PTR(&mp_type_msgpackc_UnhashableKeyException) },
    { MP_ROM_QSTR(MP_QSTR_DuplicateKeyException), MP_ROM_PTR(&mp_type_msgpackc_DuplicateKeyException) },
};
static MP_DEFINE_CONST_DICT(msgpackc_module_globals, msgpackc_module_globals_table);

const mp_obj_module_t mp_module_msgpackc = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&msgpackc_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_msgpackc, mp_module_msgpackc);
