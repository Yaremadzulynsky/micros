"""Keep immutable trust-anchor DER in flash with Mbed TLS's no-copy ownership model.

The pinned 2.16 SDK predates mbedtls_x509_crt_parse_der_nocopy. Backport only
that API's buffer ownership; certificate parsing and verification stay unchanged.
"""
import re
import ssl


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Unexpected pinned X.509 source: " + old[:70])
    return source.replace(old, new)


def patch_x509_header(source):
    source = replace_once(source, "    mbedtls_x509_buf raw;",
                          "    int own_buffer; /* Raw DER is owned only for copying parses. */\n    mbedtls_x509_buf raw;")
    return replace_once(source, "int mbedtls_x509_crt_parse_der(",
        "/* buf must remain immutable and alive until the chain is freed. */\n"
        "int mbedtls_x509_crt_parse_der_nocopy(mbedtls_x509_crt *chain,\n"
        "                                    const unsigned char *buf, size_t buflen);\n\n"
        "int mbedtls_x509_crt_parse_der(")


def patch_x509_source(source):
    source = replace_once(source,
        "static int x509_crt_parse_der_core( mbedtls_x509_crt *crt, const unsigned char *buf,\n                                    size_t buflen )",
        "static int x509_crt_parse_der_core( mbedtls_x509_crt *crt, const unsigned char *buf,\n                                    size_t buflen, int make_copy )")
    start = source.index("    // Create and populate a new buffer for the raw field")
    end = source.index("\n    /*", start)
    source = source[:start] + """    crt->raw.len = crt_end - buf;
    crt->own_buffer = make_copy;
    if( make_copy )
    {
        crt->raw.p = p = mbedtls_calloc( 1, crt->raw.len );
        if( p == NULL )
            return( MBEDTLS_ERR_X509_ALLOC_FAILED );
        memcpy( p, buf, crt->raw.len );
        p += crt->raw.len - len;
    }
    else
        crt->raw.p = (unsigned char *) buf;
    end = crt_end = p + len;
""" + source[end:]
    source = replace_once(source,
        "int mbedtls_x509_crt_parse_der( mbedtls_x509_crt *chain, const unsigned char *buf,\n                        size_t buflen )",
        "static int x509_crt_parse_der_internal( mbedtls_x509_crt *chain, const unsigned char *buf,\n                        size_t buflen, int make_copy )")
    source = replace_once(source, "x509_crt_parse_der_core( crt, buf, buflen )",
                          "x509_crt_parse_der_core( crt, buf, buflen, make_copy )")
    source = replace_once(source, "int mbedtls_x509_crt_parse( mbedtls_x509_crt *chain,",
        "int mbedtls_x509_crt_parse_der( mbedtls_x509_crt *chain, const unsigned char *buf, size_t buflen )\n"
        "{ return x509_crt_parse_der_internal( chain, buf, buflen, 1 ); }\n\n"
        "int mbedtls_x509_crt_parse_der_nocopy( mbedtls_x509_crt *chain, const unsigned char *buf, size_t buflen )\n"
        "{ return x509_crt_parse_der_internal( chain, buf, buflen, 0 ); }\n\n"
        "int mbedtls_x509_crt_parse( mbedtls_x509_crt *chain,")
    return replace_once(source, "if( cert_cur->raw.p != NULL )",
                        "if( cert_cur->own_buffer && cert_cur->raw.p != NULL )")


def trust_header(pem):
    """Generate flash-resident DER for every validated root, with no trust pruning."""
    roots = [ssl.PEM_cert_to_DER_cert(value) for value in re.findall(
        r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S)]
    if not roots:
        raise ValueError("No relay trust anchors")
    out = ['#include "mbedtls/x509_crt.h"',
           'extern const unsigned char micros_relay_pem[] asm("_binary_relay_roots_pem_start");']
    for index, root in enumerate(roots):
        out.append(f'static const unsigned char micros_root_{index}[] = {{')
        out.extend(','.join(f'0x{value:02x}' for value in root[offset:offset+16]) + ','
                   for offset in range(0, len(root), 16))
        out.append('};')
    out.extend(['static int micros_parse_relay_ca(mbedtls_x509_crt *chain,',
                ' const unsigned char *buffer, size_t bytes) {',
                ' if (buffer != micros_relay_pem)',
                '  return mbedtls_x509_crt_parse(chain, buffer, bytes);', ' int result;'])
    for index in range(len(roots)):
        out.append(f' result = mbedtls_x509_crt_parse_der_nocopy(chain, micros_root_{index}, sizeof(micros_root_{index}));')
        out.append(' if (result != 0) return result;')
    out.extend([' return 0;', '}'])
    return '\n'.join(out) + '\n'


def patch_ca_loader(source, header):
    source = replace_once(source, '#include "esp_tls_mbedtls.h"',
                          '#include "esp_tls_mbedtls.h"\n#include "' + str(header) + '"')
    return replace_once(source,
        'mbedtls_x509_crt_parse(tls->cacert_ptr, cacert, cacert_len)',
        'micros_parse_relay_ca(tls->cacert_ptr, cacert, cacert_len)')
