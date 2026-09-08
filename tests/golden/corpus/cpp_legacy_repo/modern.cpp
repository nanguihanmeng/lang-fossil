#include <iostream>
#include <memory>

class Widget {
public:
    Widget() noexcept {}
    int size() const { return 0; }
};

int main() {
    std::unique_ptr<int> p(new int(1));
    std::cout << *p << "\n";
    return 0;
}
