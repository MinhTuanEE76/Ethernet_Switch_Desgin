#pragma once
#include <stdbool.h>
void http_client_init(void);
void http_poll_config(void);
void http_update_status(bool relay_on, int uptime_minutes);