#include "http.h"
#include <assert.h>
#include <string>
struct Client
{
    std::string data;
    size_t offset = 0;
    int read(uint8_t *out, size_t count) { size_t n = std::min(count, data.size()-offset); memcpy(out,data.data()+offset,n); offset+=n; return n; }
    int read() { return offset < data.size() ? (unsigned char)data[offset++] : -1; }
};
struct Clock
{
    uint32_t tick = 0;
    uint32_t now() { return tick; }
    void idle() { ++tick; }
};
static int parse(const std::string &message, std::string *body = nullptr)
{
    Client client{message};
    Clock clock;
    uint8_t out[664];
    size_t size;
    micros_samd21::HttpReader<Client, Clock> reader(client, clock, 10);
    int code = reader.response(out, sizeof(out), size);
    if (body && code >= 200)
        *body = std::string((const char *)out, size);
    return code;
}
int main()
{
    // Consecutive replies must leave exactly the next response in the stream.
    for (const std::string &connection : {std::string(), std::string("Connection: keep-alive\r\n"), std::string("Connection: keep-alive, CLOSE \r\n")}) {
        Client client{"HTTP/1.1 200 OK\r\n"+connection+"Content-Length: 2\r\n\r\n{}HTTP/1.1 204 No Content\r\n\r\n"};
        Clock clock; uint8_t out[4]; size_t count;
        micros_samd21::HttpReader<Client,Clock> first(client,clock,10);
        assert(first.response(out,sizeof(out),count)==200 && count==2);
        assert(first.reusable()==(connection.find("CLOSE")==std::string::npos));
        micros_samd21::HttpReader<Client,Clock> second(client,clock,10);
        assert(second.response(out,sizeof(out),count)==204 && count==0 && second.reusable());
    }
    {
        Client client{"HTTP/1.0 200 OK\r\nContent-Length: 0\r\n\r\n"};
        Clock clock; uint8_t out[1]; size_t count;
        micros_samd21::HttpReader<Client,Clock> reader(client,clock,10);
        assert(reader.response(out,sizeof(out),count)==200 && !reader.reusable());
    }
    std::string body;
    const std::string prefix = "HTTP/1.1 200 OK\r\n";
    assert(
        parse(prefix + "Report-To: " + std::string(600, 'x') + "\r\nContent-Length: 4\r\n\r\nMRL1",
              &body) == 200 &&
        body == "MRL1");
    assert(parse(prefix + "Content-Length: 664\r\n\r\n" + std::string(664, 'x'), &body) == 200 &&
           body.size() == 664);
    assert(parse(prefix +
                     "Transfer-Encoding: "
                     "chunked\r\n\r\n4\r\nMRL1\r\n3;note=yes\r\nabc\r\n0\r\nTrailer: okay\r\n\r\n",
                 &body) == 200 &&
           body == "MRL1abc");
    assert(parse("HTTP/1.1 204 No Content\r\n\r\n", &body) == 204 && body.empty());
    assert(parse(prefix + "X: " + std::string(2050, 'x') + "\r\nContent-Length: 0\r\n\r\n") == -1);
    assert(parse(prefix + "Content-Length: 665\r\n\r\n") == -1);
    assert(parse(prefix + "Content-Length: 4\r\n\r\nMR") == -1);
    assert(parse(prefix + "Content-Length: 4junk\r\n\r\nMRL1") == -1);
    assert(parse(prefix + "Content-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n") ==
           -1);
    assert(parse(prefix + "Transfer-Encoding: chunked\r\n\r\nxyz\r\n") == -1);
    assert(parse(prefix + "Transfer-Encoding: chunked\r\n\r\n3\r\nabcBAD\r\n0\r\n\r\n") == -1);
    assert(parse(prefix + "Transfer-Encoding: gzip\r\n\r\n") == -1);
    // Large images stream through a fixed 256-byte buffer; incomplete/error
    // responses never become successful downloads.
    for (unsigned length : {256u, 260u, 78504u, 81920u}) {
        Client client{prefix + "Content-Length: " + std::to_string(length) + "\r\n\r\n" + std::string(length, 'a')};
        Clock clock; uint8_t buffer[256]; size_t written=0;
        micros_samd21::HttpReader<Client,Clock> reader(client,clock,1000);
        assert(reader.download(buffer,81920,[&](size_t offset,const uint8_t *data,size_t n) {
            assert(offset==written && n<=256 && n%64==0);
            for(size_t i=0;i<n;++i) assert(data[i]==(offset+i<length?'a':255));
            written+=n; return true;
        }));
        assert(written==(length+63u)/64u*64u);
    }
    for (const std::string &response : {
        prefix+"Content-Length: 81924\r\n\r\n",
        prefix+"Content-Length: 256\r\n\r\nshort",
        std::string("HTTP/1.1 404 Not Found\r\nContent-Length: 256\r\n\r\n")+std::string(256,'x'),
        prefix+"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n"}) {
        Client client{response}; Clock clock; uint8_t buffer[256];
        micros_samd21::HttpReader<Client,Clock> reader(client,clock,10);
        assert(!reader.download(buffer,81920,[](size_t,const uint8_t *,size_t){return true;}));
    }
    std::string headers;
    for (unsigned i = 0; i < 41; ++i)
        headers += "X: y\r\n";
    assert(parse(prefix + headers + "Content-Length: 0\r\n\r\n") == -1);
}
