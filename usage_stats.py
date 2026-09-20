def get_field(value,name,default=None):
    if value is None:
        return default
    if isinstance(value,dict):
        return value.get(name,default)
    return getattr(value,name,default)


def first_number(*values):
    for value in values:
        if isinstance(value,(int,float)):
            return int(value)
    return 0


def read_usage(usage):
    prompt_details=get_field(usage,"prompt_tokens_details")
    completion_details=get_field(usage,"completion_tokens_details")
    return {
        "input":get_field(usage,"prompt_tokens",0) or 0,
        "output":get_field(usage,"completion_tokens",0) or 0,
        "total":get_field(usage,"total_tokens",0) or 0,
        "cached_input":first_number(
            get_field(usage,"cached_tokens"),
            get_field(usage,"cache_read_input_tokens"),
            get_field(usage,"prompt_cache_hit_tokens"),
            get_field(prompt_details,"cached_tokens"),
            get_field(prompt_details,"cache_read_input_tokens"),
            get_field(prompt_details,"prompt_cache_hit_tokens"),
        ),
        "cache_miss_input":first_number(
            get_field(usage,"prompt_cache_miss_tokens"),
            get_field(prompt_details,"prompt_cache_miss_tokens"),
        ),
        "reasoning":get_field(completion_details,"reasoning_tokens",0) or 0,
    }
