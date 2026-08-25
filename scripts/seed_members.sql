IF OBJECT_ID(N'dbo.Members', N'U') IS NOT NULL DROP TABLE dbo.Members;
CREATE TABLE dbo.Members (
    FullName NVARCHAR(150) NOT NULL,
    NationalID CHAR(10) NOT NULL,
    HomeAddress NVARCHAR(300) NULL,
    Phone NVARCHAR(40) NULL
);
INSERT INTO dbo.Members (FullName, NationalID, HomeAddress, Phone)
SELECT DISTINCT
    c.FirstName + N' ' + c.LastName,
    'A' + RIGHT(REPLICATE('0', 9) + CAST(c.CustomerID AS varchar(9)), 9),
    COALESCE(a.AddressLine1 + N', ' + a.City + N', ' + a.StateProvince, N'(No address)'),
    c.Phone
FROM SalesLT.Customer c
LEFT JOIN SalesLT.CustomerAddress ca
       ON ca.CustomerID = c.CustomerID AND ca.AddressType = N'Main Office'
LEFT JOIN SalesLT.Address a ON a.AddressID = ca.AddressID;
