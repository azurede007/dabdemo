# Databricks notebook source
# MAGIC %md
# MAGIC ### Read from Volume & Store Raw Data

# COMMAND ----------


from pyspark.sql.functions import *

# Read raw log file
logpath= "/Volumes/inceptez_catalog/inputdb/serverlogs/accesslogs/"
raw_df = spark.read.text(logpath)

# Add metadata
bronze_df = raw_df.withColumn("ingestion_time", current_timestamp())

# Write to Bronze Delta
bronze_df.write.format("delta") \
    .mode("append") \
    .saveAsTable("workspace.bronze.logs_bronze_raw")



# COMMAND ----------

# MAGIC %md
# MAGIC ### Parse Log Fields

# COMMAND ----------

from pyspark.sql.functions import split, col

parsed_df = bronze_df.select(
    split(col("value"), " ").getItem(0).alias("date"),
    split(col("value"), " ").getItem(1).alias("time"),
    split(col("value"), " ").getItem(2).alias("log_level"),
    split(col("value"), " ").getItem(3).alias("ip_address"),
    split(col("value"), " ").getItem(4).alias("user_id"),
    split(col("value"), " ").getItem(5).alias("event_type"),
    col("ingestion_time")
)

silver_df = parsed_df.withColumn(
    "event_timestamp",
    to_timestamp(concat_ws(" ", "date", "time"))
)


# COMMAND ----------

# MAGIC %md
# MAGIC ### Data Cleaning

# COMMAND ----------

silver_clean_df = silver_df.filter(
    col("log_level").isNotNull() &
    col("ip_address").isNotNull()
)


# COMMAND ----------

# MAGIC %md
# MAGIC ###IP Location Lookup

# COMMAND ----------

ip_data = [
    ("192.168.1.10", "India", "Chennai"),
    ("192.168.1.20", "India", "Bangalore"),
    ("192.168.1.30", "India", "Hyderabad")
]

ip_schema = ["ip_address", "country", "city"]

ip_df = spark.createDataFrame(ip_data, ip_schema)

ip_df.write.format("delta") \
    .mode("overwrite") \
    .saveAsTable("ip_lookup")


# COMMAND ----------

# MAGIC %md
# MAGIC ###User Master Table

# COMMAND ----------

user_data = [
    ("user101", "Admin"),
    ("user102", "Customer"),
    ("user103", "Support")
]

user_schema = ["user_id", "user_role"]

user_df = spark.createDataFrame(user_data, user_schema)

user_df.write.format("delta") \
    .mode("overwrite") \
    .saveAsTable("user_lookup")


# COMMAND ----------

# MAGIC %md
# MAGIC ###Enrichment & Join

# COMMAND ----------

ip_df = spark.read.table("ip_lookup")
user_df = spark.read.table("user_lookup")

enriched_df = silver_clean_df \
    .join(ip_df, "ip_address", "left") \
    .join(user_df, "user_id", "left")


# COMMAND ----------

# MAGIC %md
# MAGIC ###Write enriched data to the table

# COMMAND ----------

enriched_df.write.format("delta") \
    .mode("overwrite") \
    .saveAsTable("logs_silver_enriched")


# COMMAND ----------

# MAGIC %md
# MAGIC ###Generate Insights - Failed log analysis

# COMMAND ----------

failed_login_df = enriched_df.filter(
    col("event_type") == "LOGIN_FAILED"
).groupBy(
    "city", "user_role"
).count()


# COMMAND ----------

error_trend_df = enriched_df.filter(
    col("log_level") == "ERROR"
).groupBy(
    to_date("event_timestamp").alias("date")
).count()


# COMMAND ----------

user_activity_df = enriched_df.groupBy(
    "user_id", "event_type"
).count()


# COMMAND ----------

# MAGIC %md
# MAGIC ###Write insights to table

# COMMAND ----------

failed_login_df.write.format("delta") \
    .mode("overwrite") \
    .saveAsTable("logs_gold_failed_login")

error_trend_df.write.format("delta") \
    .mode("overwrite") \
    .saveAsTable("logs_gold_error_trend")

user_activity_df.write.format("delta") \
    .mode("overwrite") \
    .saveAsTable("logs_gold_user_activity")


# COMMAND ----------

# MAGIC %md
# MAGIC ###Data Quality

# COMMAND ----------

quality_df = enriched_df.filter(
    (col("event_timestamp").isNull()) |
    (col("user_id").isNull())
)

quality_df.write.format("delta") \
    .mode("append") \
    .saveAsTable("logs_bad_records")
