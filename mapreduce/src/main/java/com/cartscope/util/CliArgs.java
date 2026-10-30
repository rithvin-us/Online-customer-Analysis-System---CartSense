package com.cartscope.util;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Argument parser for the job drivers.
 *
 * <p>Accepts repeated {@code --input} values and otherwise simple
 * {@code --name value} pairs. Hadoop's {@code GenericOptionsParser} has
 * already consumed {@code -D}, {@code -conf} and friends by the time these
 * arguments arrive, so configuration overrides never reach this class.
 */
public final class CliArgs {

    private final Map<String, String> options = new LinkedHashMap<>();
    private final List<String> inputs = new ArrayList<>();

    public static CliArgs parse(String[] args) {
        CliArgs parsed = new CliArgs();
        for (int i = 0; i < args.length; i++) {
            String token = args[i];
            if (!token.startsWith("--")) {
                throw new IllegalArgumentException("unexpected argument: " + token);
            }
            String key = token.substring(2);
            if (i + 1 >= args.length) {
                throw new IllegalArgumentException("option --" + key + " requires a value");
            }
            String value = args[++i];
            if ("input".equals(key)) {
                parsed.inputs.add(value);
            } else {
                parsed.options.put(key, value);
            }
        }
        return parsed;
    }

    public List<String> inputs() {
        if (inputs.isEmpty()) {
            throw new IllegalArgumentException("at least one --input is required");
        }
        return inputs;
    }

    public String require(String key) {
        String value = options.get(key);
        if (value == null || value.isEmpty()) {
            throw new IllegalArgumentException("option --" + key + " is required");
        }
        return value;
    }

    public String optional(String key, String fallback) {
        String value = options.get(key);
        return value == null || value.isEmpty() ? fallback : value;
    }
}
