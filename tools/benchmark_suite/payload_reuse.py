"""Optional per-case reuse for producers with paired compact/full field payloads."""


def reuse_full_payload(builder, *, raw_fields):
    """Compute once when compact output equals full output minus ``raw_fields``.

    The producer must verify that projection contract against its original
    builder. Input data and options must remain immutable between paired calls;
    create one wrapper per serial case, never share it between threads. Only the
    latest input is retained. Returned dictionaries are separate; nested values
    remain shared and must be treated as immutable. Include this source in the
    external producer's identity when enabling it.
    """
    raw_fields = frozenset(raw_fields)
    last_data = last_options = last_full = None
    initialized = False
    counts = {"builds": 0, "reuses": 0}

    def same_options(options):
        if options.keys() != last_options.keys():
            return False
        for key, value in options.items():
            previous = last_options[key]
            if value is previous:
                continue
            try:
                if not bool(value == previous):
                    return False
            except Exception:
                return False
        return True

    def build(data, *, include_raw_mesh=False, **options):
        nonlocal initialized, last_data, last_options, last_full
        if not initialized or data is not last_data or not same_options(options):
            last_full = builder(data, include_raw_mesh=True, **options)
            last_data, last_options, initialized = data, options, True
            counts["builds"] += 1
        else:
            counts["reuses"] += 1
        if last_full is None:
            return None
        return {key: value for key, value in last_full.items() if include_raw_mesh or key not in raw_fields}

    build.counts = counts
    return build
