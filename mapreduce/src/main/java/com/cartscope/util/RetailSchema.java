package com.cartscope.util;

/**
 * Column layout of the raw retail CSV and of the canonical validated record.
 *
 * <p>The raw layout is the UCI Online Retail schema. The validated layout is
 * produced once, by {@code ValidationJob}, and consumed by every analytical
 * job. Doing the parsing, date interpretation and line-value arithmetic once in
 * the validation job means the five analytical jobs read a tab separated file
 * with no quoting rules and no ambiguity, and that every one of them computes
 * revenue from exactly the same numbers.
 */
public final class RetailSchema {

    private RetailSchema() {
    }

    // ---- Raw CSV (UCI Online Retail) --------------------------------------
    public static final int RAW_INVOICE_NO = 0;
    public static final int RAW_STOCK_CODE = 1;
    public static final int RAW_DESCRIPTION = 2;
    public static final int RAW_QUANTITY = 3;
    public static final int RAW_INVOICE_DATE = 4;
    public static final int RAW_UNIT_PRICE = 5;
    public static final int RAW_CUSTOMER_ID = 6;
    public static final int RAW_COUNTRY = 7;
    public static final int RAW_FIELD_COUNT = 8;

    public static final String[] RAW_HEADERS = {
            "InvoiceNo", "StockCode", "Description", "Quantity",
            "InvoiceDate", "UnitPrice", "CustomerID", "Country"
    };

    // ---- Canonical validated record (tab separated) -----------------------
    public static final int V_INVOICE_NO = 0;
    public static final int V_STOCK_CODE = 1;
    public static final int V_DESCRIPTION = 2;
    public static final int V_QUANTITY = 3;
    public static final int V_INVOICE_TS = 4;      // epoch milliseconds, UTC
    public static final int V_INVOICE_DATE = 5;    // uuuu-MM-dd HH:mm:ss
    public static final int V_MONTH = 6;           // uuuu-MM
    public static final int V_UNIT_PRICE = 7;
    public static final int V_CUSTOMER_ID = 8;     // empty string when absent
    public static final int V_COUNTRY = 9;
    public static final int V_LINE_VALUE = 10;     // signed quantity * price
    public static final int V_ABS_VALUE = 11;      // |quantity| * price
    public static final int V_CLASS = 12;          // SALE | RETURN
    public static final int V_FIELD_COUNT = 13;

    public static final String[] VALIDATED_HEADERS = {
            "invoice_no", "stock_code", "description", "quantity",
            "invoice_ts", "invoice_date", "month", "unit_price",
            "customer_id", "country", "line_value", "abs_value", "txn_class"
    };

    /** A fulfilled sale: positive quantity, positive price, not a cancellation. */
    public static final String CLASS_SALE = "SALE";
    /** A reversal: a cancellation invoice or a negative quantity line. */
    public static final String CLASS_RETURN = "RETURN";

    public static final char FIELD_SEP = '\t';
    public static final String FIELD_SEP_STR = "\t";

    /**
     * Splits a canonical validated record. Uses an explicit limit of -1 so that
     * trailing empty fields (an absent CustomerID is the common case) are kept.
     */
    public static String[] splitValidated(String line) {
        return line.split(FIELD_SEP_STR, -1);
    }
}
