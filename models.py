
import datetime as dt
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from database import Base

class User(Base):
  __tablename__ = "users"
  id = Column(Integer, primary_key=True)
  username = Column(String, unique=True, nullable=False)
  created_at = Column(DateTime, default=dt.datetime.utcnow)

class Assumptions(Base):
  __tablename__ = "assumptions"
  id = Column(Integer, primary_key=True)
  user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
  target = Column(Float, default=1_000_000.0)
  basis = Column(Integer, default=365)
  default_cagr = Column(Float, default=7.0)
  monthly_contrib = Column(Float, default=0.0)
  cash_apy = Column(Float, default=4.5)
  price_provider = Column(String, default="none")
  alpha_key = Column(String, default="")
  updated_at = Column(DateTime, default=dt.datetime.utcnow)

class Holding(Base):
  __tablename__ = "holdings"
  id = Column(Integer, primary_key=True)
  user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
  type = Column(String)
  name = Column(String)
  units = Column(Float, default=0.0)
  price = Column(Float, default=0.0)
  cagr = Column(Float, default=7.0)
  monthly_contrib = Column(Float, default=0.0)
  updated_at = Column(DateTime, default=dt.datetime.utcnow)

class PriceCache(Base):
  __tablename__ = "prices"
  id = Column(Integer, primary_key=True)
  user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
  ticker = Column(String)
  price = Column(Float)
  ts = Column(DateTime)            # UTC
  source = Column(String)

class Projection(Base):
  __tablename__ = "projections"
  id = Column(Integer, primary_key=True)
  user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
  run_at = Column(DateTime, default=dt.datetime.utcnow)
  start_total = Column(Float)
  target = Column(Float)
  basis = Column(Integer)
  millionaire_date = Column(DateTime, nullable=True)
  days_to_target = Column(Integer, nullable=True)

class ProjectionPoint(Base):
  __tablename__ = "projection_points"
  id = Column(Integer, primary_key=True)
  projection_id = Column(Integer, ForeignKey("projections.id"), nullable=False)
  day = Column(Integer)
  total = Column(Float)
