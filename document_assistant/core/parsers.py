class Parser:
    '''Base interface for reading documents'''
    def read_document(self, file_path):
        pass


class Excel(Parser):
    def read_document(self, file_path):
        pass


class Word(Parser):
    def read_document(self, file_path):
        pass


class PDF(Parser):
    def read_document(self, file_path):
        pass


class DataParser:
    '''Read file and return origin data in markdown format'''
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.parser = self._build_engine(self.file_path)

    def origin_data(self, file_path):
        '''Read document and make initial cleaning and prepare'''
        data = self.parser.read_document(self.file_path)
        return self._initial_prepare(data)


    def _build_engine(self)->Parser:
        '''Chooose the right parser for the file format'''
        pass

    def _initial_prepare(self, data):
        return data