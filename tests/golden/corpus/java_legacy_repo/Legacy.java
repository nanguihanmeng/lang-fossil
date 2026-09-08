import java.util.Hashtable;
import java.util.Vector;

public class Legacy {
    private final Vector<String> names = new Vector<String>();
    private final Hashtable<String, String> cache = new Hashtable<String, String>();

    public String build(String key) {
        StringBuffer sb = new StringBuffer();
        sb.append(key);
        Integer wrapped = new Integer(cache.size());
        return sb.toString() + wrapped + names.size();
    }

    protected void finalize() throws Throwable {
        super.finalize();
    }

    public void stopThread(Thread worker) {
        Thread.stop(worker);
    }
}
