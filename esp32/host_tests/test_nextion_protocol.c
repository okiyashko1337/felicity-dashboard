#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "nextion_protocol.h"

int main(void)
{
    const char *response =
        "comok 1,4827-0,NX4827P043_011C-Y,99,61488,ABCDEF,16777216";
    assert(nextion_connect_model_matches(response, "NX4827P043_011C-Y"));
    assert(!nextion_connect_model_matches(response, "NX4827P043_011"));
    assert(!nextion_connect_model_matches(response, "NX4827T043_011C-Y"));
    assert(!nextion_connect_model_matches("invalid", "NX4827P043_011C-Y"));

    char label[16];
    nextion_format_version_label("0.14.1", label, sizeof(label));
    assert(strcmp(label, "v.0.14.1") == 0);
    nextion_format_version_label("v.0.14.1", label, sizeof(label));
    assert(strcmp(label, "v.0.14.1") == 0);
    nextion_format_version_label("", label, sizeof(label));
    assert(strcmp(label, "v.--") == 0);
    puts("nextion protocol tests passed");
    return 0;
}
