package com.cartscope;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.time.LocalDateTime;

import com.cartscope.util.InvoiceDateParser;
import org.junit.jupiter.api.Test;

class InvoiceDateParserTest {

    @Test
    void parsesMonthFirstByDefault() {
        LocalDateTime parsed = new InvoiceDateParser(false).parse("12/1/2010 8:26");
        assertEquals(LocalDateTime.of(2010, 12, 1, 8, 26), parsed);
    }

    @Test
    void parsesDayFirstWhenAsked() {
        LocalDateTime parsed = new InvoiceDateParser(true).parse("12/1/2010 8:26");
        assertEquals(LocalDateTime.of(2010, 1, 12, 8, 26), parsed);
    }

    @Test
    void parsesIsoTimestamps() {
        InvoiceDateParser parser = new InvoiceDateParser(false);
        assertEquals(LocalDateTime.of(2011, 3, 4, 13, 45, 9), parser.parse("2011-03-04 13:45:09"));
        assertEquals(LocalDateTime.of(2011, 3, 4, 13, 45), parser.parse("2011-03-04T13:45"));
        assertEquals(LocalDateTime.of(2011, 3, 4, 0, 0), parser.parse("2011-03-04"));
    }

    @Test
    void rejectsImpossibleAndUnknownValues() {
        InvoiceDateParser parser = new InvoiceDateParser(false);
        assertNull(parser.parse("13/45/2010 99:99"));
        assertNull(parser.parse("not a date"));
        assertNull(parser.parse(""));
        assertNull(parser.parse(null));
    }

    @Test
    void roundTripsThroughEpochMillis() {
        LocalDateTime original = LocalDateTime.of(2011, 12, 9, 12, 50);
        long millis = InvoiceDateParser.toEpochMillis(original);
        assertEquals(original, InvoiceDateParser.fromEpochMillis(millis));
    }

    @Test
    void formatsCanonicalAndMonthBucket() {
        LocalDateTime timestamp = LocalDateTime.of(2011, 1, 4, 10, 0);
        assertEquals("2011-01-04 10:00:00", timestamp.format(InvoiceDateParser.CANONICAL));
        assertEquals("2011-01", timestamp.format(InvoiceDateParser.MONTH_BUCKET));
    }
}
