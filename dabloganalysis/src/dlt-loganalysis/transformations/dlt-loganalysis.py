import dlt
from pyspark.sql.functions import *


# =====================================================
# BRONZE - AUTO LOADER (STREAMING INGESTION)
# =====================================================

@dlt.table(
    name="logs_bronze_stream",
    comment="Raw streaming server logs from volume using Auto Loader",
    table_properties={"quality": "bronze"}
)
def bronze_stream():

    return (
        spark.read.text("/Volumes/inceptez_catalog/inputdb/serverlogs/accesslogs/")
        .withColumn("ingestion_time", current_timestamp())
    )


# =====================================================
# SILVER - PARSE + CLEAN (STREAMING)
# =====================================================

@dlt.table(
    name="logs_silver_stream_parsed",
    comment="Parsed streaming server logs",
    table_properties={"quality": "silver"}
)
@dlt.expect("valid_record", "value IS NOT NULL")
@dlt.expect_or_drop("valid_length", "length(value) > 10")
def silver_stream_parsed():

    df = dlt.read_stream("logs_bronze_stream")

    parsed_df = df.select(
        split(col("value"), " ").getItem(0).alias("date"),
        split(col("value"), " ").getItem(1).alias("time"),
        split(col("value"), " ").getItem(2).alias("log_level"),
        split(col("value"), " ").getItem(3).alias("ip_address"),
        split(col("value"), " ").getItem(4).alias("user_id"),
        split(col("value"), " ").getItem(5).alias("event_type"),
        col("ingestion_time")
    )

    return (
        parsed_df
        .withColumn(
            "event_timestamp",
            to_timestamp(concat_ws(" ", "date", "time"))
        )
        .withWatermark("event_timestamp", "30 minutes")
    )


# =====================================================
# LOOKUP TABLE - IP MASTER (BATCH)
# =====================================================

@dlt.table(
    name="ip_lookup",
    comment="IP to location lookup"
)
def ip_lookup():

    data = [
        ("192.168.1.10", "India", "Chennai"),
        ("192.168.1.20", "India", "Bangalore"),
        ("192.168.1.30", "India", "Hyderabad"),
        ("192.168.1.40", "India", "Mumbai"),
        ("192.168.1.50", "India", "Delhi")
    ]

    return spark.createDataFrame(
        data,
        ["ip_address", "country", "city"]
    )


# =====================================================
# LOOKUP TABLE - USER MASTER (BATCH)
# =====================================================

@dlt.table(
    name="user_lookup",
    comment="User role lookup"
)
def user_lookup():

    data = [
        ("user101", "Admin"),
        ("user102", "Customer"),
        ("user103", "Support"),
        ("user104", "Engineer"),
        ("user105", "Manager")
    ]

    return spark.createDataFrame(
        data,
        ["user_id", "user_role"]
    )


# =====================================================
# SILVER - ENRICHMENT (STREAM + BATCH JOIN)
# =====================================================

@dlt.table(
    name="logs_silver_stream_enriched",
    comment="Enriched streaming logs",
    table_properties={"quality": "silver"}
)
def silver_stream_enriched():

    logs_df = dlt.read_stream("logs_silver_stream_parsed")
    ip_df = dlt.read("ip_lookup")
    user_df = dlt.read("user_lookup")

    return (
        logs_df
        .join(ip_df, "ip_address", "left")
        .join(user_df, "user_id", "left")
    )


# =====================================================
# GOLD - FAILED LOGIN KPI (STREAMING)
# =====================================================

@dlt.table(
    name="logs_gold_stream_failed_login",
    comment="Streaming failed login KPI",
    table_properties={"quality": "gold"}
)
def gold_failed_login():

    df = dlt.read_stream("logs_silver_stream_enriched")

    return (
        df.filter(col("event_type") == "LOGIN_FAILED")
          .groupBy("city", "user_role")
          .count()
    )


# =====================================================
# GOLD - ERROR TREND (WINDOWED STREAM)
# =====================================================

@dlt.table(
    name="logs_gold_stream_error_window",
    comment="Windowed error trend",
    table_properties={"quality": "gold"}
)
def gold_error_window():

    df = dlt.read_stream("logs_silver_stream_enriched")

    return (
        df.filter(col("log_level") == "ERROR")
          .groupBy(
              window(col("event_timestamp"), "10 minutes"),
              col("city")
          )
          .count()
    )


# =====================================================
# GOLD - USER ACTIVITY (STREAMING)
# =====================================================

@dlt.table(
    name="logs_gold_stream_user_activity",
    comment="Streaming user activity summary",
    table_properties={"quality": "gold"}
)
def gold_user_activity():

    df = dlt.read_stream("logs_silver_stream_enriched")

    return (
        df.groupBy("user_id", "event_type")
          .count()
    )


# =====================================================
# BAD RECORDS / DEAD LETTER QUEUE
# =====================================================

@dlt.table(
    name="logs_bad_records",
    comment="Invalid or corrupted records"
)
@dlt.expect_or_drop("invalid_ts", "event_timestamp IS NOT NULL")
def bad_records():

    df = dlt.read_stream("logs_silver_stream_parsed")

    return df.filter(col("event_timestamp").isNull())
