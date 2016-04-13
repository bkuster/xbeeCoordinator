SELECT name, URN, UOM
FROM sensor_property
INNER JOIN observed_property
ON property_ID = ID
WHERE sensor_ID = '{0}'
ORDER BY property_ID
;
