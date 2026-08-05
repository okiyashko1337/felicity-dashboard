#pragma once

#include "device_settings.h"

/* Blocks in first-boot setup mode until settings are saved, then restarts. */
void wifi_provisioning_run(device_settings_t *settings);
