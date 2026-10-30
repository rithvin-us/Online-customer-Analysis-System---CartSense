package com.cartscope.util;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.time.format.ResolverStyle;
import java.util.List;

/**
 * Parses the {@code InvoiceDate} column.
 *
 * <p>The UCI Online Retail dataset is distributed as a spreadsheet, and the CSV
 * exports of it in circulation use month-first US formatting
 * ({@code 12/1/2010 8:26}). Other exports use ISO-8601. Rather than guessing
 * per record, the parser tries a fixed, ordered list of patterns and then
 * remembers the one that worked, so later records in the same task cost a
 * single parse attempt.
 *
 * <p>The ordering matters for ambiguous values such as {@code 3/4/2011}:
 * month-first is tried first because that is the dominant form for this
 * dataset. Set {@code cartscope.invoice.date.dayfirst=true} to prefer
 * day-first instead; the choice is recorded in the run manifest so a result
 * can always be explained.
 */
public final class InvoiceDateParser {

    public static final String CONF_DAY_FIRST = "cartscope.invoice.date.dayfirst";

    private static final DateTimeFormatter[] MONTH_FIRST = patterns(
            "M/d/uuuu H:mm", "M/d/uuuu H:mm:ss", "M/d/uu H:mm", "M/d/uuuu");
    private static final DateTimeFormatter[] DAY_FIRST = patterns(
            "d/M/uuuu H:mm", "d/M/uuuu H:mm:ss", "d/M/uu H:mm", "d/M/uuuu");
    private static final DateTimeFormatter[] ISO = patterns(
            "uuuu-MM-dd HH:mm:ss", "uuuu-MM-dd'T'HH:mm:ss", "uuuu-MM-dd HH:mm",
            "uuuu-MM-dd'T'HH:mm", "uuuu-MM-dd HH:mm:ss.SSS", "uuuu-MM-dd");

    private static DateTimeFormatter[] patterns(String... specs) {
        DateTimeFormatter[] out = new DateTimeFormatter[specs.length];
        for (int i = 0; i < specs.length; i++) {
            out[i] = DateTimeFormatter.ofPattern(specs[i]).withResolverStyle(ResolverStyle.STRICT);
        }
        return out;
    }

    /** Canonical textual form written into the validated dataset. */
    public static final DateTimeFormatter CANONICAL =
            DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss");
    /** Canonical month bucket, used as the key of the monthly sales analysis. */
    public static final DateTimeFormatter MONTH_BUCKET =
            DateTimeFormatter.ofPattern("uuuu-MM");

    private final List<DateTimeFormatter[]> order;
    private DateTimeFormatter lastSuccessful;

    public InvoiceDateParser(boolean dayFirst) {
        this.order = dayFirst
                ? List.of(DAY_FIRST, ISO, MONTH_FIRST)
                : List.of(MONTH_FIRST, ISO, DAY_FIRST);
    }

    /**
     * @return the parsed timestamp, or {@code null} when no supported pattern
     *         matches. Callers reject the record in that case; they never
     *         substitute a default date.
     */
    public LocalDateTime parse(String raw) {
        if (raw == null) {
            return null;
        }
        String value = raw.trim();
        if (value.isEmpty()) {
            return null;
        }
        if (lastSuccessful != null) {
            LocalDateTime hit = attempt(value, lastSuccessful);
            if (hit != null) {
                return hit;
            }
        }
        for (DateTimeFormatter[] family : order) {
            for (DateTimeFormatter formatter : family) {
                LocalDateTime hit = attempt(value, formatter);
                if (hit != null) {
                    lastSuccessful = formatter;
                    return hit;
                }
            }
        }
        return null;
    }

    private static LocalDateTime attempt(String value, DateTimeFormatter formatter) {
        try {
            return LocalDateTime.parse(value, formatter);
        } catch (DateTimeParseException dateTimeOnlyFailure) {
            // The pattern may be date-only; retry as a LocalDate at midnight.
            try {
                return LocalDate.parse(value, formatter).atStartOfDay();
            } catch (DateTimeParseException notThisPattern) {
                return null;
            }
        }
    }

    public static long toEpochMillis(LocalDateTime timestamp) {
        return timestamp.toInstant(ZoneOffset.UTC).toEpochMilli();
    }

    public static LocalDateTime fromEpochMillis(long millis) {
        return LocalDateTime.ofEpochSecond(millis / 1000L, (int) ((millis % 1000L) * 1_000_000L),
                ZoneOffset.UTC);
    }
}
