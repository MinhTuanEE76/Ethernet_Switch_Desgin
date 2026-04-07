#pragma once
#include <stdbool.h>
void relay_init(void);
void relay_set(bool state);
bool relay_get(void);