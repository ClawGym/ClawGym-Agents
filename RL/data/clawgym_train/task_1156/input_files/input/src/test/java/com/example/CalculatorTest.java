package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class CalculatorTest {

    @Test
    void divideByZeroThrows() {
        Calculator c = new Calculator();
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class, () -> c.divide(10, 0));
        assertEquals("Division by zero", ex.getMessage());
    }

    @Test
    void normalDivide() {
        Calculator c = new Calculator();
        assertEquals(5, c.divide(10, 2));
    }
}
