package com.cartscope;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.cartscope.util.CsvLineParser;
import org.junit.jupiter.api.Test;

class CsvLineParserTest {

    private final CsvLineParser parser = new CsvLineParser();

    @Test
    void splitsPlainFields() {
        CsvLineParser.Result result = parser.parse("536365,85123A,WHITE HANGING HEART,6,12/1/2010 8:26,2.55,17850,United Kingdom");
        assertFalse(result.malformed());
        assertEquals(8, result.size());
        assertEquals("85123A", result.get(1));
        assertEquals("United Kingdom", result.get(7));
    }

    @Test
    void keepsCommasInsideQuotedDescription() {
        CsvLineParser.Result result =
                parser.parse("536370,22728,\"SET/6 RED SPOTTY PAPER CUPS, LARGE\",24,12/1/2010 8:45,0.85,12583,France");
        assertFalse(result.malformed());
        assertEquals(8, result.size());
        assertEquals("SET/6 RED SPOTTY PAPER CUPS, LARGE", result.get(2));
        assertEquals("France", result.get(7));
    }

    @Test
    void unescapesDoubledQuotes() {
        CsvLineParser.Result result = parser.parse("A,\"say \"\"hi\"\" now\",C");
        assertFalse(result.malformed());
        assertEquals("say \"hi\" now", result.get(1));
    }

    @Test
    void keepsTrailingEmptyField() {
        CsvLineParser.Result result = parser.parse("536414,22139,NO CUSTOMER,56,12/1/2010 11:52,0.0,,United Kingdom");
        assertEquals(8, result.size());
        assertEquals("", result.get(6));
    }

    @Test
    void reportsUnterminatedQuoteAsMalformed() {
        CsvLineParser.Result result = parser.parse("A,\"broken across lines,C");
        assertTrue(result.malformed());
    }

    @Test
    void returnsEmptyStringBeyondLastField() {
        CsvLineParser.Result result = parser.parse("A,B");
        assertEquals("", result.get(7));
    }
}
