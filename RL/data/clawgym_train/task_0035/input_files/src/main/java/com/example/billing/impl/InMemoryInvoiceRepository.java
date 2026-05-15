package com.example.billing.impl;

import com.example.billing.Invoice;
import com.example.billing.InvoiceRepository;

public class InMemoryInvoiceRepository implements InvoiceRepository {
    @Override
    public Invoice findById(String id) {
        // TODO: replace with persistent storage
        return new Invoice(id, 0.0);
    }
}
