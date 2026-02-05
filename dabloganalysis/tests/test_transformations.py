from pyspark.sql import SparkSession
import pytest

@pytest.fixture(scope="session")
def spark():
    return SparkSession.builder.master("local[1]").getOrCreate()

def test_transformation(spark):
    df = spark.createDataFrame([(1, "a")], ["id", "val"])
    assert df.count() == 1