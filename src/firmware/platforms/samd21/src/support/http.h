#ifndef MICROS_SAMD21_HTTP_H
#define MICROS_SAMD21_HTTP_H
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

namespace micros_samd21
{
// A small bounded HTTP/1 response reader. Unknown headers are drained even
// when their values exceed the scratch buffer (e.g. Cloudflare Report-To).
template <class Client, class Clock> class HttpReader
{
    Client &client;
    Clock &clock;
    uint32_t deadline;
    int byte()
    {
        while ((int32_t)(deadline - clock.now()) > 0)
        {
            int c = client.read();
            if (c >= 0)
                return c;
            clock.idle();
        }
        return -1;
    }
    int line(char *out, size_t capacity)
    {
        size_t used = 0, total = 0;
        for (;;)
        {
            int c = byte();
            if (c < 0 || ++total > 2048)
                return -1;
            if (c == '\n')
            {
                out[used] = 0;
                return (int)used;
            }
            if (c != '\r' && used + 1 < capacity)
                out[used++] = (char)c;
        }
    }
    static bool number(const char *text, unsigned base, size_t limit, size_t &value, bool extension)
    {
        while (*text == ' ' || *text == '\t')
            ++text;
        value = 0;
        unsigned digits = 0;
        for (;; ++text)
        {
            unsigned d = *text >= '0' && *text <= '9'   ? *text - '0'
                         : *text >= 'a' && *text <= 'f' ? *text - 'a' + 10
                         : *text >= 'A' && *text <= 'F' ? *text - 'A' + 10
                                                        : 99;
            if (d >= base)
                break;
            if (d > limit || value > (limit - d) / base)
                return false;
            value = value * base + d;
            ++digits;
        }
        while (*text == ' ' || *text == '\t')
            ++text;
        return digits && (!*text || (extension && *text == ';'));
    }
    bool payload(uint8_t *out, size_t count)
    {
        for (size_t i = 0; i < count; ++i)
        {
            int c = byte();
            if (c < 0)
                return false;
            out[i] = c;
        }
        return true;
    }

  public:
    HttpReader(Client &input, Clock &timer, uint32_t timeout = 10000)
        : client(input), clock(timer), deadline(timer.now() + timeout)
    {
    }
    int headers(size_t capacity, size_t &length, bool &chunked)
    {
        char scratch[192];
        unsigned status = 0;
        if (line(scratch, sizeof(scratch)) < 0 ||
            (strncmp(scratch, "HTTP/1.1 ", 9) && strncmp(scratch, "HTTP/1.0 ", 9)) ||
            sscanf(scratch + 9, "%u", &status) != 1 || status < 200 || status > 599)
            return -1;
        bool has_length = false;
        chunked = false; length = 0;
        for (unsigned headers = 0;; ++headers)
        {
            int n = line(scratch, sizeof(scratch));
            if (n < 0 || headers >= 40)
                return -1;
            if (!n)
                break;
            if (!strncasecmp(scratch, "Content-Length:", 15))
            {
                if (has_length || !number(scratch + 15, 10, capacity, length, false))
                    return -1;
                has_length = true;
            }
            if (!strncasecmp(scratch, "Transfer-Encoding:", 18))
            {
                char *value = scratch + 18;
                while (*value == ' ' || *value == '\t')
                    ++value;
                char *end = value + strlen(value);
                while (end > value && (end[-1] == ' ' || end[-1] == '\t'))
                    *--end = 0;
                if (chunked || strcasecmp(value, "chunked"))
                    return -1;
                chunked = true;
            }
        }
        if (!chunked && !has_length && status != 204) return -1;
        if (chunked && has_length)
            return -1;
        return (int)status;
    }
    int response(uint8_t *out, size_t capacity, size_t &received)
    {
        received = 0;
        size_t length; bool chunked;
        int status = headers(capacity, length, chunked);
        if (status < 0) return -1;
        char scratch[192];
        if (!chunked)
        {
            if (!payload(out, length))
                return -1;
            received = length;
            return (int)status;
        }
        for (;;)
        {
            size_t size;
            if (line(scratch, sizeof(scratch)) < 0 ||
                !number(scratch, 16, capacity - received, size, true))
                return -1;
            if (!size)
            {
                for (unsigned trailers = 0; trailers < 40; ++trailers)
                {
                    int n = line(scratch, sizeof(scratch));
                    if (n < 0)
                        return -1;
                    if (!n)
                        return (int)status;
                }
                return -1;
            }
            if (!payload(out + received, size) || byte() != '\r' || byte() != '\n')
                return -1;
            received += size;
        }
    }
    // The image endpoint supplies Content-Length; never flash error bodies or
    // ambiguous/chunked framing. Reuse caller-owned scratch memory for SPI reads.
    template<class Sink> bool download(uint8_t *buffer, size_t capacity, Sink sink)
    {
        size_t length; bool chunked;
        if (headers(capacity, length, chunked) != 200 || chunked || length < 256 || length % 4)
            return false;
        for (size_t offset = 0; offset < length; offset += 256)
        {
            size_t count = length - offset;
            if (count > 256) count = 256;
            size_t used = 0;
            while (used < count && (int32_t)(deadline - clock.now()) > 0)
            {
                int n = client.read(buffer + used, count - used);
                if (n > 0) used += n;
                else clock.idle();
            }
            if (used != count) return false;
            size_t padded = (count + 63) & ~(size_t)63;
            memset(buffer + count, 255, padded - count);
            if (!sink(offset, buffer, padded)) return false;
            clock.idle();
        }
        return true;
    }

};
} // namespace micros_samd21
#endif
