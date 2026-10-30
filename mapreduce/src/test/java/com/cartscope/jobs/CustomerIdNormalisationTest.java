package com.cartscope.jobs;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class CustomerIdNormalisationTest {

    @Test
    void stripsSpreadsheetFloatArtefact() {
        assertEquals("17850", ValidationJob.CanonicaliseMapper.normaliseCustomerId("17850.0"));
        assertEquals("17850", ValidationJob.CanonicaliseMapper.normaliseCustomerId(" 17850 "));
    }

    @Test
    void treatsPlaceholdersAsMissing() {
        assertEquals("", ValidationJob.CanonicaliseMapper.normaliseCustomerId(""));
        assertEquals("", ValidationJob.CanonicaliseMapper.normaliseCustomerId("  "));
        assertEquals("", ValidationJob.CanonicaliseMapper.normaliseCustomerId("NA"));
        assertEquals("", ValidationJob.CanonicaliseMapper.normaliseCustomerId("nan"));
        assertEquals("", ValidationJob.CanonicaliseMapper.normaliseCustomerId("NULL"));
    }

    @Test
    void replacesCanonicalSeparators() {
        assertEquals("A B C", ValidationJob.CanonicaliseMapper.sanitise("A\tB\nC"));
        assertEquals("plain", ValidationJob.CanonicaliseMapper.sanitise("plain"));
    }
}
