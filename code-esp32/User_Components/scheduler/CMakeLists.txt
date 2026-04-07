idf_component_register(
    SRCS "scheduler.c"
    INCLUDE_DIRS "."
    REQUIRES relay time_sync scheduler esp_timer http_client
)