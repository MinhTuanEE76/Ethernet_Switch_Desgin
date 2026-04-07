#include "relay.h"
#include "driver/gpio.h"
#include "esp_log.h"

#define RELAY_PIN   GPIO_NUM_18
#define LED_PIN     GPIO_NUM_3

static bool relay_state = false;

void relay_init(void) {
    gpio_reset_pin(RELAY_PIN);
    gpio_set_direction(RELAY_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(RELAY_PIN, 0);

    gpio_reset_pin(LED_PIN);
    gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(LED_PIN, 0);

    relay_state = false;
    ESP_LOGI("RELAY", "Relay initialized");
}

void relay_set(bool state) {
    relay_state = state;
    gpio_set_level(RELAY_PIN, state ? 1 : 0);
    gpio_set_level(LED_PIN, state ? 1 : 0);
    ESP_LOGI("RELAY", "Relay set %s", state ? "ON" : "OFF");
}

bool relay_get(void) {
    return relay_state;
}