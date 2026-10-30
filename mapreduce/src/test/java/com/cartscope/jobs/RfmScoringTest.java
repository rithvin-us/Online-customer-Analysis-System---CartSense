package com.cartscope.jobs;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class RfmScoringTest {

    @Test
    void quintileSpansOneToFive() {
        double[] population = new double[100];
        for (int i = 0; i < population.length; i++) {
            population[i] = i;
        }
        assertEquals(1, RfmAnalysisJob.ScoringReducer.quintile(population, 0));
        assertEquals(1, RfmAnalysisJob.ScoringReducer.quintile(population, 19));
        assertEquals(2, RfmAnalysisJob.ScoringReducer.quintile(population, 20));
        assertEquals(3, RfmAnalysisJob.ScoringReducer.quintile(population, 40));
        assertEquals(5, RfmAnalysisJob.ScoringReducer.quintile(population, 99));
    }

    @Test
    void quintileHandlesSingleCustomerPopulation() {
        assertEquals(1, RfmAnalysisJob.ScoringReducer.quintile(new double[] {42.0d}, 42.0d));
    }

    @Test
    void segmentRulesMatchTheDocumentedTable() {
        assertEquals(RfmAnalysisJob.SEGMENT_HIGH_VALUE,
                RfmAnalysisJob.ScoringReducer.segmentOf(5, 5, 5));
        assertEquals(RfmAnalysisJob.SEGMENT_LOYAL,
                RfmAnalysisJob.ScoringReducer.segmentOf(2, 4, 3));
        assertEquals(RfmAnalysisJob.SEGMENT_NEW,
                RfmAnalysisJob.ScoringReducer.segmentOf(5, 1, 1));
        assertEquals(RfmAnalysisJob.SEGMENT_POTENTIAL,
                RfmAnalysisJob.ScoringReducer.segmentOf(3, 3, 1));
        assertEquals(RfmAnalysisJob.SEGMENT_AT_RISK,
                RfmAnalysisJob.ScoringReducer.segmentOf(1, 3, 1));
        assertEquals(RfmAnalysisJob.SEGMENT_ATTENTION,
                RfmAnalysisJob.ScoringReducer.segmentOf(1, 1, 1));
    }
}
