#ifndef MICROS_CONTROLLER_H
#define MICROS_CONTROLLER_H
#ifdef __cplusplus
extern "C" {
#endif
void micros_controller_run(void);
/* Borrow the reserved response, or NULL while a transport owns it.
 * Only the controller task may request replies. The consuming transport must
 * release after its final read; no heap allocation is involved. */
char *micros_controller_rpc_reply(char *line, int physical);
void micros_controller_rpc_release(char *reply);
void micros_controller_remote_line(char *line, int physical);
#ifdef __cplusplus
}
#endif
#endif
