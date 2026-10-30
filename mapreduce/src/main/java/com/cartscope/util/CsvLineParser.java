package com.cartscope.util;

import java.util.ArrayList;
import java.util.List;

/**
 * A small RFC 4180 compliant CSV field splitter.
 *
 * <p>The retail dataset this platform targets contains product descriptions
 * such as {@code "SET/6 RED SPOTTY PAPER CUPS, LARGE"}, so splitting a line on
 * commas corrupts records. This parser understands quoted fields, embedded
 * delimiters and doubled escape quotes ({@code ""}).
 *
 * <p>One deliberate limitation: a single call parses a single physical line.
 * Hadoop's {@code TextInputFormat} delivers records split on newlines, so a
 * quoted field containing a literal newline cannot be reassembled here. Such a
 * line ends with an unterminated quote, which {@link #parse} reports through
 * {@link Result#malformed()} so the caller can reject the record rather than
 * silently mis-parse it. The ingestion stage counts multi-line records up front
 * and surfaces the count in the data quality report.
 */
public final class CsvLineParser {

    private final char delimiter;
    private final char quote;

    public CsvLineParser() {
        this(',', '"');
    }

    public CsvLineParser(char delimiter, char quote) {
        this.delimiter = delimiter;
        this.quote = quote;
    }

    /** Outcome of parsing one line: either the fields, or a malformed flag. */
    public static final class Result {
        private final List<String> fields;
        private final boolean malformed;

        private Result(List<String> fields, boolean malformed) {
            this.fields = fields;
            this.malformed = malformed;
        }

        public List<String> fields() {
            return fields;
        }

        public boolean malformed() {
            return malformed;
        }

        public int size() {
            return fields.size();
        }

        /** Field at {@code index}, trimmed, or an empty string when absent. */
        public String get(int index) {
            if (index < 0 || index >= fields.size()) {
                return "";
            }
            return fields.get(index).trim();
        }
    }

    public Result parse(String line) {
        List<String> fields = new ArrayList<>(12);
        StringBuilder current = new StringBuilder();
        boolean inQuotes = false;

        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);

            if (inQuotes) {
                if (c == quote) {
                    // A doubled quote inside a quoted field is a literal quote.
                    if (i + 1 < line.length() && line.charAt(i + 1) == quote) {
                        current.append(quote);
                        i++;
                    } else {
                        inQuotes = false;
                    }
                } else {
                    current.append(c);
                }
                continue;
            }

            if (c == quote) {
                // A quote appearing after unquoted text (A"B) is tolerated as
                // the start of a quoted section; the common real-world case is
                // a field that is entirely quoted.
                inQuotes = true;
            } else if (c == delimiter) {
                fields.add(current.toString());
                current.setLength(0);
            } else {
                current.append(c);
            }
        }
        fields.add(current.toString());

        // Still inside a quoted field at end of line: the record is truncated
        // because the original CSV field contained a newline.
        return new Result(fields, inQuotes);
    }
}
