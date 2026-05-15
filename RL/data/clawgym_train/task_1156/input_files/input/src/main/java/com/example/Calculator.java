package com.example;

public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }

    public int divide(int a, int b) {
        // Beginner's incorrect attempt to "handle" division by zero
        if (b == 0) {
            return 0; // TODO: maybe better to throw an exception?
        }
        return a / b;
    }
}
