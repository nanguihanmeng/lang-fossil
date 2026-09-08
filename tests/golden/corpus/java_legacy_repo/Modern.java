import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class Modern {
    private final List<String> names = new ArrayList<String>();
    private final Map<String, String> cache = new HashMap<String, String>();

    public String build(String key) {
        StringBuilder sb = new StringBuilder();
        sb.append(key);
        Integer wrapped = Integer.valueOf(cache.size());
        return sb.toString() + wrapped + names.size();
    }
}
