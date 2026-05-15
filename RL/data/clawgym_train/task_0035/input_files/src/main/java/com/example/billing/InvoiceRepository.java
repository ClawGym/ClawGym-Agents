package com.example.billing;

public interface InvoiceRepository {
    Invoice findById(String id);
}
