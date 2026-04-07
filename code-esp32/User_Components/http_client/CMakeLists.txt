idf_component_register(
    SRCS "http_client.c"
    INCLUDE_DIRS "."
    REQUIRES relay time_sync scheduler json esp_http_client
)