SELECT sensor_ID,
    COUNT(DISTINCT(time_utc)) as ticker,
    MIN(time_utc) as last,
    MAX(time_utc) as newest
FROM observation
GROUP BY sensor_ID
ORDER BY ticker ASC
;
