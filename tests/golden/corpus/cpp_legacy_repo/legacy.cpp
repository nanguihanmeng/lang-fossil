#include <iostream.h>
#include <memory>

class Widget {
public:
    Widget() throw() {}
};

int main() {
    register int i = 0;
    std::auto_ptr<int> p(new int(1));
    return i;
}
