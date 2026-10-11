#ifndef MICROS_CONTROLLER_H
#define MICROS_CONTROLLER_H
#ifdef __cplusplus
extern "C" {
#endif
void micros_controller_run(void);
/* Returns an owned reply buffer, or NULL on allocation failure. Caller frees it. */
char *micros_controller_rpc_reply(char *line, int physical);
void micros_controller_remote_line(char *line, int physical);
#ifdef __cplusplus
}
#endif
#endif
