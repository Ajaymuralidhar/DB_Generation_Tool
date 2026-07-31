CREATE OR REPLACE FUNCTION fn_calculate_tax(p_price IN NUMBER) 
RETURN NUMBER IS
    v_tax_rate CONSTANT NUMBER := 0.0825; -- 8.25% tax
BEGIN
    RETURN ROUND(p_price + (p_price * v_tax_rate), 2);
END;
/