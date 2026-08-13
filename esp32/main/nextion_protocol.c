#include "nextion_protocol.h"

#include <stddef.h>
#include <string.h>

bool nextion_connect_model_matches(const char *response,
                                   const char *expected_model)
{
    if (!response || !expected_model || !expected_model[0]) return false;
    const char *connect = strstr(response, "comok ");
    if (!connect) return false;
    const char *field = strchr(connect, ',');
    if (!field || !(field = strchr(field + 1, ','))) return false;
    ++field;
    const char *end = strchr(field, ',');
    size_t actual_length = end ? (size_t)(end - field) : strlen(field);
    return strlen(expected_model) == actual_length &&
           strncmp(field, expected_model, actual_length) == 0;
}
