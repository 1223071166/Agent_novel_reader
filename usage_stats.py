usage_total={
    "input":0,
    "output":0,
    "total":0,
    "cached_input":0,
    "cache_miss_input":0,
    "reasoning":0,
}


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


def display_usage(current):
    for key in usage_total:
        usage_total[key]+=current[key]
    print(f"[usage] input={current['input']} output={current['output']} total={current['total']} cached_input={current['cached_input']} cache_miss_input={current['cache_miss_input']} reasoning={current['reasoning']}")
    print(f"[usage cumulative] input={usage_total['input']} output={usage_total['output']} total={usage_total['total']} cached_input={usage_total['cached_input']} cache_miss_input={usage_total['cache_miss_input']} reasoning={usage_total['reasoning']}")
