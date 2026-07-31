CREATE OR REPLACE PROCEDURE sp_restock_product(
    p_product_id IN NUMBER, 
    p_added_qty IN NUMBER
) IS
BEGIN
    UPDATE PRODUCTS 
    SET STOCK_QTY = STOCK_QTY + p_added_qty 
    WHERE PRODUCT_ID = p_product_id;
    
    COMMIT;
END;
/