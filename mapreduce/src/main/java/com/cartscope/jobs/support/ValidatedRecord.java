package com.cartscope.jobs.support;

import com.cartscope.util.RetailSchema;

/**
 * A mutable view over one line of the canonical validated dataset.
 *
 * <p>Mappers reuse a single instance per task, so parsing a split allocates
 * one object rather than one per record. {@link #parse} returns false for a
 * line that does not match the canonical layout, which lets a mapper count it
 * and move on instead of failing the whole task.
 */
public final class ValidatedRecord {

    private String invoiceNo = "";
    private String stockCode = "";
    private String description = "";
    private String customerId = "";
    private String country = "";
    private String month = "";
    private long quantity;
    private long invoiceTimestamp;
    private double unitPrice;
    private double lineValue;
    private double absValue;
    private boolean sale;

    public boolean parse(String line) {
        String[] fields = RetailSchema.splitValidated(line);
        if (fields.length < RetailSchema.V_FIELD_COUNT) {
            return false;
        }
        try {
            quantity = Long.parseLong(fields[RetailSchema.V_QUANTITY]);
            invoiceTimestamp = Long.parseLong(fields[RetailSchema.V_INVOICE_TS]);
            unitPrice = Double.parseDouble(fields[RetailSchema.V_UNIT_PRICE]);
            lineValue = Double.parseDouble(fields[RetailSchema.V_LINE_VALUE]);
            absValue = Double.parseDouble(fields[RetailSchema.V_ABS_VALUE]);
        } catch (NumberFormatException notCanonical) {
            return false;
        }
        invoiceNo = fields[RetailSchema.V_INVOICE_NO];
        stockCode = fields[RetailSchema.V_STOCK_CODE];
        description = fields[RetailSchema.V_DESCRIPTION];
        month = fields[RetailSchema.V_MONTH];
        customerId = fields[RetailSchema.V_CUSTOMER_ID];
        country = fields[RetailSchema.V_COUNTRY];
        sale = RetailSchema.CLASS_SALE.equals(fields[RetailSchema.V_CLASS]);
        return true;
    }

    public String invoiceNo() {
        return invoiceNo;
    }

    public String stockCode() {
        return stockCode;
    }

    public String description() {
        return description;
    }

    public String customerId() {
        return customerId;
    }

    public boolean hasCustomerId() {
        return !customerId.isEmpty();
    }

    public String country() {
        return country;
    }

    public String month() {
        return month;
    }

    public long quantity() {
        return quantity;
    }

    public long invoiceTimestamp() {
        return invoiceTimestamp;
    }

    public double unitPrice() {
        return unitPrice;
    }

    /** Signed value of the line: negative for a negative quantity. */
    public double lineValue() {
        return lineValue;
    }

    /** Magnitude of the line value, used to total up returns. */
    public double absValue() {
        return absValue;
    }

    /** True for a fulfilled sale, false for a return or cancellation. */
    public boolean isSale() {
        return sale;
    }
}
