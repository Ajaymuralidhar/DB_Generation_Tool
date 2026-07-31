CREATE OR REPLACE PROCEDURE record_transaction (
    p_account_id IN NUMBER,
    p_trans_type IN NUMBER,
    p_amount     IN FLOAT,
    p_remarks    IN VARCHAR2
) AS
BEGIN
    -- 1. Insert the new transaction record
    INSERT INTO TransactionDetails (AccountID, TransactionType, TransactionDate, TransactionAmt, Remarks)
    VALUES (p_account_id, p_trans_type, SYSDATE, p_amount, p_remarks);

    -- 2. Update the account balance dynamically
    IF p_trans_type = 1 THEN
        -- Debit (Subtract from balance)
        UPDATE AccountBalance 
        SET BalAmount = BalAmount - p_amount,
            LasteupdateTS = SYSDATE
        WHERE AccountID = p_account_id;
    ELSIF p_trans_type = 2 THEN
        -- Credit (Add to balance)
        UPDATE AccountBalance 
        SET BalAmount = BalAmount + p_amount,
            LasteupdateTS = SYSDATE
        WHERE AccountID = p_account_id;
    END IF;

    COMMIT;
END record_transaction;
/
