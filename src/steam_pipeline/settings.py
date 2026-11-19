# Los entornos cambian solo las claves indicadas y conservan el resto.
CONFIG_LOADER_ARGS = {
    "base_env": "base",
    "default_run_env": "local",
    "merge_strategy": {"parameters": "soft"},
}
