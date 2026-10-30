package com.cartscope.util;

/**
 * Minimal JSON writer.
 *
 * <p>Job reports are the contract between the Java jobs and the Python
 * backend, so they are written with no third-party serialiser: the job jar
 * stays dependency-free and cannot be broken by a Jackson version difference
 * between the build and the cluster.
 */
public final class Json {

    private final StringBuilder out = new StringBuilder(4096);
    private boolean needsComma;

    public Json beginObject() {
        separate();
        out.append('{');
        needsComma = false;
        return this;
    }

    public Json endObject() {
        out.append('}');
        needsComma = true;
        return this;
    }

    public Json beginArray() {
        separate();
        out.append('[');
        needsComma = false;
        return this;
    }

    public Json endArray() {
        out.append(']');
        needsComma = true;
        return this;
    }

    public Json name(String key) {
        separate();
        quote(key);
        out.append(':');
        needsComma = false;
        return this;
    }

    public Json value(String text) {
        separate();
        if (text == null) {
            out.append("null");
        } else {
            quote(text);
        }
        needsComma = true;
        return this;
    }

    public Json value(long number) {
        separate();
        out.append(number);
        needsComma = true;
        return this;
    }

    public Json value(double number) {
        separate();
        if (Double.isNaN(number) || Double.isInfinite(number)) {
            out.append("null");
        } else {
            out.append(number);
        }
        needsComma = true;
        return this;
    }

    public Json value(boolean flag) {
        separate();
        out.append(flag);
        needsComma = true;
        return this;
    }

    public Json field(String key, String text) {
        return name(key).value(text);
    }

    public Json field(String key, long number) {
        return name(key).value(number);
    }

    public Json field(String key, double number) {
        return name(key).value(number);
    }

    public Json field(String key, boolean flag) {
        return name(key).value(flag);
    }

    private void separate() {
        if (needsComma) {
            out.append(',');
            needsComma = false;
        }
    }

    private void quote(String text) {
        out.append('"');
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                case '\b' -> out.append("\\b");
                case '\f' -> out.append("\\f");
                default -> {
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
                }
            }
        }
        out.append('"');
    }

    @Override
    public String toString() {
        return out.toString();
    }
}
