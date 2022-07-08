import typing as tp
import datetime

from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import ForeignKey, select
from sqlalchemy.orm import relationship

Base = declarative_base()


class Spare(Base):
    __tablename__ = 'spares'
    SpareId = Column(Integer, name='SpareId', primary_key=True)
    PartNumber = Column(String, name='PartNumber')
    Manufacturer = Column(String)
    Name = Column(String)
    Link = Column(String)
    CarId = Column(Integer, ForeignKey("cars.CarId"))
    cars = relationship("Car", back_populates="spares")


class Car(Base):
    __tablename__ = 'cars'
    __table_args__ = {'extend_existing': True}
    CarId = Column(Integer, primary_key=True)
    Name = Column(String)
    spares = relationship("Spare", back_populates="cars", uselist=True)


class ZapBaseHandler:
    def __init__(self):
        pass

    def __del__(self):
        self.teardown()

    def connect(self, sqlite_database_name: str) -> str:
        """
        Initialize all the context for working with database here
        :param sqlite_database_name: path to the sqlite3 database file
        """
        need_to_create = False
        if sqlite_database_name is None:
            need_to_create = True
            sqlite_database_name = "tmp" + str(datetime.datetime.now()) + ".sqlite3"
        self.engine_ = create_engine('sqlite+pysqlite:///' + sqlite_database_name, echo=True)
        if need_to_create:
            Base.metadata.create_all(self.engine_)
        Session = sessionmaker(bind=self.engine_, future=True, expire_on_commit=False)
        self.session_ = Session()
        return sqlite_database_name

    def carlist(self) -> tp.Sequence[tp.Tuple[str, str]]:
        """
        Return car list
        :return:
        """
        cars = self.session_.execute(select(Car)).scalars().all()
        return [(i.CarId, i.Name) for i in cars]

    def spareslist(self) -> tp.Sequence[tp.Tuple[str, str, str, str, str]]:
        """
        Return spares list
        :return:
        """
        spares = self.session_.execute(select(Spare)).scalars().all()
        sparelist = []
        for spare in spares:
            carname = "None"
            if spare.cars:
                carname = spare.cars.Name
            sparelist.append((spare.PartNumber, spare.Manufacturer, spare.Name, spare.Link, carname))
        return sparelist

    def search(self, partname: str) -> tp.Sequence[tp.Tuple[str, str, str, str, str]]:
        """
        Return spares list
        :return:
        """
        spares = self.session_.execute(
            select(Spare).where(Spare.Name.contains(partname.lower()))).scalars().all()
        sparelist = []
        for spare in spares:
            carname = "None"
            if spare.cars:
                carname = spare.cars.Name
                sparelist.append((spare.PartNumber, spare.Manufacturer, spare.Name, spare.Link, carname))
        return sparelist

    def addcar(self, name: str) -> None:
        """
        Add car to bd
        :return:
        """
        car = Car(Name=name)
        self.session_.add(car)
        self.session_.commit()
        pass

    def addspare(self, spare: tuple[str, str, str, str, str]) -> None:
        """
        Add car to bd
        :return:
        """
        sp = Spare(PartNumber=spare[0], Manufacturer=spare[1], Name=spare[2].lower(), Link=spare[3], CarId=spare[4])
        self.session_.add(sp)
        self.session_.commit()

    def teardown(self) -> None:
        """
        Cleanup everything after working with database.
        Do anything that may be needed or leave blank
        :return:
        """
        self.session_.close()
