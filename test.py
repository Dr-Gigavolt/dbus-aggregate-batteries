from functions import Functions

class TestClass:
    def __init__(self):
        self.fn = Functions()
        


def main():
    tc = TestClass()
    XX = [2.4, 2.5, 2.55]
    YY = [1, 0.1, 0]
    print(tc.fn._interpolate(XX, YY, 2.45))
    print(tc.fn._max(XX))
    print(tc.fn._min(XX))
      

if __name__ == "__main__":
	main()
        

