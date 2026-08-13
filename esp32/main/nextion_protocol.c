#include "nextion_protocol.h"

#include <stddef.h>
#include <stdio.h>
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

void nextion_format_version_label(const char *version, char *label,
                                  size_t label_size)
{
    if (!label || label_size == 0) return;
    if (!version || !version[0]) {
        snprintf(label, label_size, "v.--");
        return;
    }
    while (*version == 'v' || *version == 'V' || *version == '.') ++version;
    snprintf(label, label_size, "v.%s", version[0] ? version : "--");
}
