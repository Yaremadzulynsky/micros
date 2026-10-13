/* User-owned handler implementations; generation never overwrites this file. */
#include "state.h"

_Static_assert(COUNTER_GET_VALUE_HANDLER_SCHEMA == UINT64_C(0x2d2dcbeea1e32c92), "counter_get_value: command schema changed; review handler and update expected schema");
micros_result_t counter_get_value(const micros_service_args_t *service,
    const counter_get_value_request_t *request, counter_get_value_response_t *response)
{
    (void)request;
    counter_t *state = service->arena;
    response->value = state->value;
    return MICROS_OK;
}

_Static_assert(COUNTER_SET_VALUE_HANDLER_SCHEMA == UINT64_C(0x3270e5ee8b6b0b2d), "counter_set_value: command schema changed; review handler and update expected schema");
micros_result_t counter_set_value(const micros_service_args_t *service,
    const counter_set_value_request_t *request, counter_set_value_response_t *response)
{
    counter_t *state = service->arena;
    state->value = request->value;
    response->value = state->value;
    return MICROS_OK;
}
